#!/usr/bin/env python3
import argparse
import csv
import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import logging
from collections import Counter

from database import IncidentDatabase
from incident_validator import validate_incident
from ccnews_collector import CCNewsCollector
from rss_collector import RSSCollector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

with open('config.yaml', 'r') as f:
    CONFIG = yaml.safe_load(f)


class JournalistSafetyMonitor:
    def __init__(self, use_database: bool = True, shard_count: int = 1, shard_index: int = 0):
        self.db = IncidentDatabase() if use_database else None
        self.shard_count = max(shard_count, 1)
        self.shard_index = shard_index % self.shard_count

        collection_config = CONFIG.get('ccnews_collection', {})
        self.ccnews = CCNewsCollector(
            CONFIG,
            shard_count=self.shard_count,
            shard_index=self.shard_index,
            timeout=collection_config.get('request_timeout_seconds', 60),
        )
        # RSS feeds are cheap (a handful of small HTTP requests), unlike
        # WARC files, so every shard polls all of them rather than sharding.
        self.rss = RSSCollector(CONFIG)

        self.validation_config = CONFIG.get('validation', {})
        self.start_time = datetime.now()
        self.stats = {
            'ccnews_files_processed': 0,
            'rss_feeds_polled': 0,
            'articles_collected': 0,
            'new_incidents': 0,
            'duplicate_incidents': 0,
            'validated_articles': 0,
            'candidate_articles': 0,
            'rejected_articles': 0,
        }
        self.validation_decisions = []

    def _validate_article(self, article: Dict, matched_source: str) -> Dict:
        validation = validate_incident(article)
        decision = {
            'url': article.get('url', ''),
            'title': article.get('title', ''),
            'domain': article.get('domain', ''),
            'source_country': article.get('country', ''),
            'language': article.get('language', ''),
            'published_date': article.get('published_date', ''),
            'matched_query': matched_source,
            'validation_status': validation.status,
            'incident_type': validation.incident_type or '',
            'severity': validation.severity or '',
            'validation_reason': validation.reason,
            'evidence_text': validation.evidence_text,
        }

        incident = None
        if validation.status == 'validated':
            incident = {
                'url': article.get('url', ''),
                'title': article.get('title', ''),
                'date': article.get('published_date', ''),
                'domain': article.get('domain', ''),
                'country': article.get('country', ''),
                'severity': validation.severity,
                'incident_type': validation.incident_type,
                'description': validation.evidence_text or article.get('description', '')[:1000] or article.get('title', ''),
                'language': article.get('language', ''),
                'source_country': article.get('country', ''),
                'matched_query': matched_source,
                'validation_status': validation.status,
                'validation_reason': validation.reason,
                'evidence_text': validation.evidence_text,
            }

        return {'decision': decision, 'incident': incident}

    def _collect_articles(self) -> List[Dict]:
        articles: List[Dict] = []

        try:
            ccnews_articles = self.ccnews.collect()
            articles.extend(ccnews_articles)
            self.stats['ccnews_files_processed'] = len(self.ccnews.last_files_processed)
        except Exception as e:
            logger.error(f"CC-NEWS collection failed: {e}")

        try:
            rss_articles = self.rss.collect()
            articles.extend(rss_articles)
            self.stats['rss_feeds_polled'] = self.rss.last_feeds_polled
        except Exception as e:
            logger.error(f"RSS collection failed: {e}")

        return articles

    def collect_incidents(self):
        logger.info("Starting incident collection...")
        articles = self._collect_articles()
        self.stats['articles_collected'] = len(articles)
        logger.info(f"Collected {len(articles)} articles from CC-NEWS + RSS")

        all_incidents = []
        for article in articles:
            matched_source = f"{article.get('source', 'unknown')}:{article.get('domain', '')}"
            validated = self._validate_article(article, matched_source)
            self.validation_decisions.append(validated['decision'])
            status = validated['decision']['validation_status']
            if status == 'validated':
                self.stats['validated_articles'] += 1
            elif status == 'candidate':
                self.stats['candidate_articles'] += 1
            elif status == 'rejected':
                self.stats['rejected_articles'] += 1
            if validated['incident']:
                all_incidents.append(validated['incident'])

        if all_incidents and self.db:
            new_count, dup_count = self.db.bulk_insert_incidents(all_incidents)
            self.stats['new_incidents'] = new_count
            self.stats['duplicate_incidents'] = dup_count
            logger.info(f"Stored {new_count} new incidents")

        if self.db:
            review_decisions = [
                decision
                for decision in self.validation_decisions
                if decision['validation_status'] in {'candidate', 'rejected'}
            ]
            candidate_count, _ = self.db.bulk_insert_candidates(review_decisions)
            logger.info(f"Stored {candidate_count} candidate/rejected article decisions")

        self.export_validation_decisions()

        return all_incidents

    def export_validation_decisions(self):
        if not self.validation_decisions or not self.validation_config.get('export_decisions', True):
            return

        decisions = self._filter_validation_decisions(self.validation_decisions)
        if not decisions:
            logger.info("No validation decisions matched export policy")
            return

        output_dir = Path(self.validation_config.get('debug_dir', 'data/debug'))
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = output_dir / f'validation_decisions_{timestamp}.csv'

        fieldnames = [
            'url', 'title', 'published_date', 'domain', 'source_country',
            'language', 'matched_query', 'validation_status', 'incident_type',
            'severity', 'validation_reason', 'evidence_text',
        ]

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(decisions)

        logger.info(f"Validation decisions exported to {output_path}")

    def _filter_validation_decisions(self, decisions: List[Dict]) -> List[Dict]:
        export_candidates = self.validation_config.get('export_candidates', True)
        export_rejected = self.validation_config.get('export_rejected', False)
        export_validated = self.validation_config.get('export_validated', True)

        allowed_statuses = set()
        if export_validated:
            allowed_statuses.add('validated')
        if export_candidates:
            allowed_statuses.add('candidate')
        if export_rejected:
            allowed_statuses.add('rejected')

        return [d for d in decisions if d.get('validation_status') in allowed_statuses]

    def dry_run(self, max_articles: Optional[int] = None):
        logger.info("Starting dry run...")
        articles = self._collect_articles()
        if max_articles:
            articles = articles[:max_articles]
        self.stats['articles_collected'] = len(articles)

        totals = Counter()
        examples = {'validated': [], 'candidate': [], 'rejected': []}

        print(f"Collected {len(articles)} articles in dry-run mode "
              f"({self.stats['ccnews_files_processed']} CC-NEWS files, "
              f"{self.stats['rss_feeds_polled']} RSS feeds)")
        print("-" * 80)

        for article in articles:
            matched_source = f"{article.get('source', 'unknown')}:{article.get('domain', '')}"
            validated = self._validate_article(article, matched_source)
            decision = validated['decision']
            status = decision['validation_status']
            totals[status] += 1
            if len(examples[status]) < 5:
                examples[status].append(decision)

        print(f"Validation totals: {dict(totals)}")

        for status in ['validated', 'candidate', 'rejected']:
            if not examples[status]:
                continue
            print(f"\n{status.title()} examples:")
            for decision in examples[status]:
                print(f"- {decision['title']} ({decision['domain']}, {decision['language']})")
                print(f"  source={decision['matched_query']}")
                print(f"  reason={decision['validation_reason']}")

        return {
            'status': 'SUCCESS',
            'stats': self.stats,
            'validation_totals': dict(totals),
        }

    def analyze_data(self) -> Dict:
        if not self.db:
            raise RuntimeError("Database is not available")
        logger.info("Analyzing data...")
        stats = self.db.get_statistics(days=CONFIG['lookback_days'], validation_status='validated')
        rankings = self.db.get_country_rankings(days=CONFIG['lookback_days'], validation_status='validated')
        trend_data = self.db.get_trend_data(days=CONFIG['lookback_days'], validation_status='validated')
        incident_types = self.db.get_incident_types_breakdown(days=CONFIG['lookback_days'], validation_status='validated')

        return {
            'statistics': stats,
            'country_rankings': rankings,
            'trend_data': trend_data,
            'incident_types': incident_types,
            'critical_incidents': self.db.get_incidents_by_severity('CRITICAL', days=7, validation_status='validated'),
        }

    def generate_report(self, analysis: Dict):
        logger.info("Generating report...")
        report_date = datetime.now().strftime('%Y-%m-%d')
        report_path = Path(f'reports/report_{report_date}.md')
        report_path.parent.mkdir(parents=True, exist_ok=True)

        stats = analysis['statistics']

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# Journalist Safety Report (CC-NEWS) - {report_date}\n\n")
            f.write("## Executive Summary\n\n")
            f.write(f"Total Incidents (Last {CONFIG['lookback_days']} days): {stats['total_incidents']}\n")
            f.write(f"Critical Incidents: {stats['critical']}\n")
            f.write(f"High Severity: {stats['high']}\n")
            f.write(f"Countries Affected: {stats['unique_countries']}\n\n")
            f.write("## Collection Metadata\n\n")
            f.write(f"- CC-NEWS shard: {self.shard_index + 1}/{self.shard_count}\n")
            f.write(f"- CC-NEWS files processed: {self.stats['ccnews_files_processed']}\n")
            f.write(f"- RSS feeds polled: {self.stats['rss_feeds_polled']}\n")
            f.write(f"- Articles collected: {self.stats['articles_collected']}\n")
            f.write(f"- Validated articles: {self.stats['validated_articles']}\n")
            f.write(f"- Candidate articles: {self.stats['candidate_articles']}\n")
            f.write(f"- Rejected articles: {self.stats['rejected_articles']}\n")
            f.write(f"- New incidents: {self.stats['new_incidents']}\n")
            f.write(f"- Duplicates filtered: {self.stats['duplicate_incidents']}\n")
            execution_time = (datetime.now() - self.start_time).total_seconds()
            f.write(f"- Execution time: {execution_time:.1f} seconds\n")

        logger.info(f"Report saved: {report_path}")

    def generate_alerts(self, analysis: Dict):
        critical = analysis['critical_incidents']
        if not critical:
            logger.info("No critical alerts")
            return None

        alert_date = datetime.now().strftime('%Y-%m-%d')
        alert_path = Path(f'alerts/critical_alerts_{alert_date}.json')
        alert_path.parent.mkdir(parents=True, exist_ok=True)

        alerts = {'timestamp': datetime.now().isoformat(), 'alert_count': len(critical), 'incidents': critical}
        with open(alert_path, 'w') as f:
            json.dump(alerts, f, indent=2)

        logger.info(f"Critical alerts: {alert_path}")

    def apply_data_retention(self):
        retention_days = CONFIG.get('data_retention', {}).get('database_days')
        if not retention_days:
            return

        if self.stats['articles_collected'] == 0:
            logger.info("Skipping retention because this run collected no articles")
            return

        logger.info(f"Applying database retention: {retention_days} days")
        self.db.purge_old_data(retention_days)

    def export_data(self):
        logger.info("Exporting data...")
        self.db.export_to_csv('data/exports/incidents_full.csv', validation_status='validated')

        windows = CONFIG.get('data_retention', {}).get('rolling_export_windows', [])
        if not windows:
            logger.info("Data exported")
            return

        for window in windows:
            label = window['label']
            days = window['days']
            self.db.export_to_csv(f'data/exports/incidents_{label}.csv', days=days, validation_status='validated')

        candidate_window_days = CONFIG.get('validation', {}).get('candidate_export_days', 10)
        self.db.export_candidates_to_csv('data/exports/candidates_full.csv')
        self.db.export_candidates_to_csv('data/exports/candidates_10d.csv', days=candidate_window_days)

        logger.info("Rolling data exports saved")

    def save_statistics(self, analysis: Dict):
        today = datetime.now().strftime('%Y-%m-%d')
        stats = analysis['statistics']
        stats['queries_executed'] = self.stats['ccnews_files_processed'] + self.stats['rss_feeds_polled']
        self.db.save_daily_stats(today, stats)
        logger.info("Statistics saved")

    def run(self):
        status = 'ERROR'
        try:
            logger.info("=" * 80)
            logger.info("JOURNALIST SAFETY MONITORING SYSTEM (CC-NEWS)")
            logger.info("=" * 80)

            incidents = self.collect_incidents()
            self.apply_data_retention()
            analysis = self.analyze_data()
            self.generate_report(analysis)
            self.generate_alerts(analysis)
            self.export_data()
            self.save_statistics(analysis)
            status = 'SUCCESS'

            logger.info("=" * 80)
            logger.info("MONITORING COMPLETE")
            logger.info("=" * 80)

            return {'status': 'SUCCESS', 'stats': self.stats, 'analysis': analysis}
        except Exception as e:
            logger.error(f"Error: {e}")
            raise
        finally:
            if self.db:
                execution_time = (datetime.now() - self.start_time).total_seconds()
                self.db.log_collection_run({
                    'run_date': datetime.now().isoformat(),
                    'queries_executed': self.stats['ccnews_files_processed'] + self.stats['rss_feeds_polled'],
                    'articles_collected': self.stats['articles_collected'],
                    'new_incidents': self.stats['new_incidents'],
                    'execution_time': execution_time,
                    'status': status,
                })
            self.rss.close()
            if self.db:
                self.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run the journalist safety monitor (CC-NEWS + RSS)")
    parser.add_argument('--dry-run', action='store_true', help='Collect and validate without writing files or database rows')
    parser.add_argument('--max-articles', type=int, default=None, help='Limit the number of collected articles, useful with --dry-run')
    parser.add_argument('--shard-count', type=int, default=1, help='Split CC-NEWS WARC files into this many shards')
    parser.add_argument('--shard-index', type=int, default=0, help='Run only this zero-based shard index')
    args = parser.parse_args()

    monitor = JournalistSafetyMonitor(
        use_database=not args.dry_run,
        shard_count=args.shard_count,
        shard_index=args.shard_index,
    )
    if args.dry_run:
        results = monitor.dry_run(max_articles=args.max_articles)
        monitor.rss.close()
    else:
        results = monitor.run()

    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)
    if args.dry_run:
        print(f"Articles collected: {results['stats']['articles_collected']}")
        print(f"Validation totals: {results['validation_totals']}")
    else:
        print(f"New incidents: {results['stats']['new_incidents']}")
        print(f"Total in database: {results['analysis']['statistics']['total_incidents']}")
    print("=" * 80)
