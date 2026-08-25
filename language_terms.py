#!/usr/bin/env python3
"""
Per-language term lists for incident_validator.py.

English's term lists live in incident_validator.py itself (unchanged, so its
regression tests stay byte-for-byte identical); this module adds a
registry of LanguageTerms for the languages picked up by the 2026-08-25
source expansion (see PLAN.md) that aren't English: Spanish, Portuguese,
Russian, Italian, French. All are whitespace-delimited scripts where the
existing \\b-based term matching works mechanically as-is.

Arabic and Farsi are deliberately NOT included yet: their definite article
attaches directly to the noun with no space (e.g. Arabic "الصحفي" = "the
journalist" as a single token), so a plain \\bصحفي\\b term won't match
inside it -- that needs prefixed word-form variants, which is follow-up
work, not a copy-paste extension of this module.

Translations here are rule-based vocabulary lists, not run through a
translation API or reviewed by a native speaker of each language -- treat
them as a first pass tuned for common journalism-safety reporting register,
worth revisiting if a language's false-positive/negative rate looks off in
practice.

negation_prefixes: unlike English's negation (auxiliary verb + n't/not,
e.g. "did not"), these languages put a negation particle directly before
the verb (Spanish/Portuguese/Italian: no/não/non; French: pas/jamais/plus,
appearing after the auxiliary in compound tenses like "n'a pas tué";
Russian: не). Each prefix is matched the same way English's is: only when
it sits within a couple of words directly before a recognized action term,
not just anywhere nearby in the sentence (see incident_validator.py's
NEGATED_ACTION_RE comment for why that distinction matters).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class LanguageTerms:
    media_subject_terms: List[str]
    action_terms_by_type: Dict[str, List[str]]
    source_attribution_patterns: List[str]
    retrospective_patterns: List[str]
    negation_prefixes: List[str]
    extra_negatable_actions: List[str] = field(default_factory=list)


SPANISH = LanguageTerms(
    media_subject_terms=[
        "periodista", "periodistas",
        "periodista estudiantil", "periodistas estudiantiles",
        "estudiante de periodismo", "estudiantes de periodismo",
        "reportero", "reportera", "reporteros", "reporteras",
        "corresponsal", "corresponsales",
        "corresponsal de guerra", "corresponsales de guerra",
        "fotoperiodista", "fotoperiodistas",
        "camarógrafo", "camarógrafa", "camarógrafos", "camarógrafas",
        "editor", "editora", "editores", "editoras",
        "columnista", "columnistas",
        "locutor", "locutora", "locutores", "locutoras",
        "trabajador de prensa", "trabajadora de prensa",
        "trabajadores de prensa", "trabajadoras de prensa",
        "trabajador de medios", "trabajadores de medios",
        "equipo de prensa", "equipo periodístico",
        "periódico",
        "redacción",
        "medio de comunicación", "medio de prensa",
        "estación de radio",
        "estación de televisión", "canal de televisión",
    ],
    action_terms_by_type={
        "KILLING": [
            "asesinado", "asesinada", "asesinados", "asesinadas",
            "muerto a tiros", "murió a tiros",
            "apuñalado hasta la muerte", "apuñalada hasta la muerte",
            "golpeado hasta la muerte", "golpeada hasta la muerte",
            "encontrado muerto", "encontrada muerta",
            "asesinado a tiros",
        ],
        "DETENTION": [
            "detenido", "detenida", "detenidos", "detenidas",
            "arrestado", "arrestada", "arrestados", "arrestadas",
            "encarcelado", "encarcelada",
            "sentenciado", "sentenciada", "condenado", "condenada",
            "bajo custodia", "puesto en custodia", "puesta en custodia",
        ],
        "ATTACK": [
            "atacado", "atacada", "atacados", "atacadas",
            "agredido", "agredida",
            "golpeado", "golpeada",
            "baleado", "baleada",
            "apuñalado", "apuñalada",
            "herido", "herida",
            "secuestrado", "secuestrada",
            "torturado", "torturada",
        ],
        "THREAT": [
            "amenazado", "amenazada",
            "amenaza de muerte", "amenazas de muerte",
            "acosado", "acosada",
            "intimidado", "intimidada",
        ],
        "CENSORSHIP": [
            "censurado", "censurada",
            "prohibido", "prohibida",
            "bloqueado", "bloqueada",
            "clausurado", "clausurada", "cerrado", "cerrada",
            "suspendido", "suspendida",
            "allanado", "allanada",
        ],
        "DISAPPEARANCE": [
            "desaparecido", "desaparecida", "desaparecidos", "desaparecidas",
            "desaparecido forzosamente", "desaparecida forzosamente",
        ],
    },
    source_attribution_patterns=[
        r"\b(?:periodista|reportero|reportera|corresponsal|editor|editora)\s+(?:informa|inform[oó]|dice|dijo|escribe|escribi[oó]|afirma|afirm[oó])\b",
        r"\bseg[uú]n\s+(?:un|una|el|la)?\s*(?:periodista|reportero|reportera|corresponsal)\b",
        r"\bdijo\s+a\s+(?:los\s+|las\s+)?(?:periodistas|reporteros|reporteras|corresponsales|la prensa)\b",
        r"\bhabl[oó]\s+con\s+(?:periodistas|reporteros|la prensa)\b",
        r"\breportes?\s+de\s+(?:prensa|medios)\b",
        r"\brueda de prensa\b|\bconferencia de prensa\b",
        r"\bcomunicado de prensa\b",
    ],
    retrospective_patterns=[
        r"\b(?:\d+|un|una)\s+(?:a[nñ]os?|meses?)\s+(?:despu[eé]s|m[aá]s tarde)\b",
        r"\baniversario\b",
        r"\brecordando\b|\ba un a[nñ]o (?:de|del)\b",
        r"\ben esta fecha\b|\bhace \d+ a[nñ]os?\b",
    ],
    negation_prefixes=[r"\bno", r"\bnunca", r"\bjam[aá]s"],
    extra_negatable_actions=["da[nñ]ado", "da[nñ]ada", "lastimado", "lastimada"],
)


PORTUGUESE = LanguageTerms(
    media_subject_terms=[
        "jornalista", "jornalistas",
        "estudante de jornalismo", "estudantes de jornalismo",
        "repórter", "repórteres",
        "correspondente", "correspondentes",
        "correspondente de guerra",
        "fotojornalista", "fotojornalistas",
        "cinegrafista", "cinegrafistas",
        "editor", "editora", "editores", "editoras",
        "colunista", "colunistas",
        "locutor", "locutora", "locutores", "locutoras",
        "trabalhador de imprensa", "trabalhadora de imprensa",
        "trabalhadores de imprensa", "trabalhadoras de imprensa",
        "equipe de reportagem",
        "jornal",
        "redação",
        "veículo de comunicação", "veículo de imprensa",
        "estação de rádio",
        "emissora de televisão", "canal de televisão",
    ],
    action_terms_by_type={
        "KILLING": [
            "assassinado", "assassinada", "assassinados", "assassinadas",
            "morto a tiros", "morta a tiros",
            "esfaqueado até a morte", "esfaqueada até a morte",
            "espancado até a morte", "espancada até a morte",
            "encontrado morto", "encontrada morta",
        ],
        "DETENTION": [
            "detido", "detida", "detidos", "detidas",
            "preso", "presa", "presos", "presas",
            "encarcerado", "encarcerada",
            "sentenciado", "sentenciada", "condenado", "condenada",
            "sob custódia",
        ],
        "ATTACK": [
            "atacado", "atacada",
            "agredido", "agredida",
            "espancado", "espancada",
            "baleado", "baleada",
            "esfaqueado", "esfaqueada",
            "ferido", "ferida",
            "sequestrado", "sequestrada",
            "torturado", "torturada",
        ],
        "THREAT": [
            "ameaçado", "ameaçada",
            "ameaça de morte", "ameaças de morte",
            "assediado", "assediada",
            "intimidado", "intimidada",
        ],
        "CENSORSHIP": [
            "censurado", "censurada",
            "proibido", "proibida",
            "bloqueado", "bloqueada",
            "fechado", "fechada",
            "suspenso", "suspensa",
            "invadido", "invadida",
        ],
        "DISAPPEARANCE": [
            "desaparecido", "desaparecida", "desaparecidos", "desaparecidas",
            "desaparecido à força", "desaparecida à força",
        ],
    },
    source_attribution_patterns=[
        r"\b(?:jornalista|repórter|correspondente|editor|editora)\s+(?:informa|informou|diz|disse|escreve|escreveu|afirma|afirmou)\b",
        r"\bsegundo\s+(?:um|uma)?\s*(?:jornalista|repórter|correspondente)\b",
        r"\bdisse\s+a(?:os)?\s+(?:jornalistas|repórteres|à imprensa)\b",
        r"\bfalou\s+com\s+(?:jornalistas|repórteres|a imprensa)\b",
        r"\brelatos? da imprensa\b",
        r"\bcoletiva de imprensa\b|\bentrevista coletiva\b",
        r"\bnota (?:de|à) imprensa\b|\bcomunicado de imprensa\b",
    ],
    retrospective_patterns=[
        r"\b(?:\d+|um|uma)\s+(?:anos?|meses?)\s+(?:depois|ap[oó]s|mais tarde)\b",
        r"\baniversário\b",
        r"\brelembrando\b|\bum ano depois\b",
        r"\bnesta data\b",
    ],
    negation_prefixes=[r"\bn[ãa]o", r"\bnunca", r"\bjamais"],
    extra_negatable_actions=["prejudicado", "prejudicada", "machucado", "machucada"],
)


ITALIAN = LanguageTerms(
    media_subject_terms=[
        "giornalista", "giornalisti", "giornaliste",
        "studente di giornalismo", "studentessa di giornalismo",
        "cronista", "cronisti", "croniste",
        "corrispondente", "corrispondenti",
        "corrispondente di guerra",
        "fotoreporter",
        "operatore video", "operatrice video", "operatori video",
        "redattore", "redattrice", "redattori", "redattrici",
        "editorialista", "editorialisti",
        "conduttore", "conduttrice",
        "lavoratore dei media", "lavoratrice dei media", "lavoratori dei media",
        "troupe giornalistica",
        "giornale",
        "redazione",
        "testata giornalistica", "testata",
        "stazione radiofonica",
        "emittente televisiva", "canale televisivo",
    ],
    action_terms_by_type={
        "KILLING": [
            "assassinato", "assassinata", "assassinati", "assassinate",
            "ucciso", "uccisa", "uccisi", "uccise",
            "ucciso a colpi di arma da fuoco", "uccisa a colpi di arma da fuoco",
            "accoltellato a morte", "accoltellata a morte",
            "picchiato a morte", "picchiata a morte",
            "trovato morto", "trovata morta",
        ],
        "DETENTION": [
            "detenuto", "detenuta", "detenuti", "detenute",
            "arrestato", "arrestata", "arrestati", "arrestate",
            "incarcerato", "incarcerata",
            "condannato", "condannata",
            "in custodia",
        ],
        "ATTACK": [
            "attaccato", "attaccata",
            "aggredito", "aggredita",
            "picchiato", "picchiata",
            "colpito con arma da fuoco", "colpita con arma da fuoco",
            "accoltellato", "accoltellata",
            "ferito", "ferita",
            "rapito", "rapita",
            "torturato", "torturata",
        ],
        "THREAT": [
            "minacciato", "minacciata",
            "minaccia di morte", "minacce di morte",
            "molestato", "molestata",
            "intimidito", "intimidita",
        ],
        "CENSORSHIP": [
            "censurato", "censurata",
            "vietato", "vietata",
            "bloccato", "bloccata",
            "chiuso", "chiusa",
            "sospeso", "sospesa",
            "perquisito", "perquisita",
        ],
        "DISAPPEARANCE": [
            "scomparso", "scomparsa",
            "fatto sparire", "fatta sparire",
        ],
    },
    source_attribution_patterns=[
        r"\b(?:giornalista|cronista|corrispondente|redattore|redattrice)\s+(?:riferisce|ha riferito|dice|ha detto|scrive|ha scritto|afferma|ha affermato)\b",
        r"\bsecondo\s+(?:un|una)?\s*(?:giornalista|cronista|corrispondente)\b",
        r"\bha detto\s+ai\s+(?:giornalisti|cronisti|reporter)\b",
        r"\bha parlato\s+con\s+(?:i\s+)?(?:giornalisti|cronisti|la stampa)\b",
        r"\bfonti di stampa\b",
        r"\bconferenza stampa\b",
        r"\bcomunicato stampa\b",
    ],
    retrospective_patterns=[
        r"\b(?:\d+|un|una)\s+(?:anni|mesi)\s+(?:dopo|fa)\b",
        r"\banniversario\b",
        # No trailing \b after "da": Italian elides it directly onto the
        # next word with an apostrophe ("dall'assassinio"), so requiring a
        # boundary right after "da" would miss the contracted form.
        r"\bricordando\b|\bad un anno da",
        r"\bin questo giorno\b",
    ],
    negation_prefixes=[r"\bnon", r"\bmai"],
    extra_negatable_actions=["danneggiato", "danneggiata", "leso", "lesa"],
)


FRENCH = LanguageTerms(
    media_subject_terms=[
        "journaliste", "journalistes",
        "étudiant en journalisme", "étudiante en journalisme",
        "reporter", "reporters",
        "correspondant", "correspondante", "correspondants", "correspondantes",
        "correspondant de guerre",
        "photojournaliste", "photojournalistes",
        "cadreur", "cadreuse", "cadreurs", "cadreuses",
        "caméraman", "caméramans",
        "rédacteur", "rédactrice", "rédacteurs", "rédactrices",
        "chroniqueur", "chroniqueuse", "chroniqueurs", "chroniqueuses",
        "animateur", "animatrice",
        "travailleur des médias", "travailleuse des médias", "travailleurs des médias",
        "équipe de reportage",
        "journal",
        "rédaction",
        "média", "organe de presse",
        "station de radio",
        "chaîne de télévision",
    ],
    action_terms_by_type={
        "KILLING": [
            "assassiné", "assassinée", "assassinés", "assassinées",
            "tué", "tuée", "tués", "tuées",
            "tué par balles", "tuée par balles",
            "poignardé à mort", "poignardée à mort",
            "battu à mort", "battue à mort",
            "retrouvé mort", "retrouvée morte",
        ],
        "DETENTION": [
            "détenu", "détenue", "détenus", "détenues",
            "arrêté", "arrêtée", "arrêtés", "arrêtées",
            "emprisonné", "emprisonnée",
            "condamné", "condamnée",
            "placé en garde à vue", "placée en garde à vue",
        ],
        "ATTACK": [
            "attaqué", "attaquée",
            "agressé", "agressée",
            "battu", "battue",
            "abattu", "abattue",
            "poignardé", "poignardée",
            "blessé", "blessée",
            "enlevé", "enlevée",
            "torturé", "torturée",
        ],
        "THREAT": [
            "menacé", "menacée",
            "menace de mort", "menaces de mort",
            "harcelé", "harcelée",
            "intimidé", "intimidée",
        ],
        "CENSORSHIP": [
            "censuré", "censurée",
            "interdit", "interdite",
            "bloqué", "bloquée",
            "fermé", "fermée",
            "suspendu", "suspendue",
            "perquisitionné", "perquisitionnée",
        ],
        "DISAPPEARANCE": [
            "disparu", "disparue",
            "porté disparu", "portée disparue",
            "fait disparaître de force", "faite disparaître de force",
        ],
    },
    source_attribution_patterns=[
        r"\b(?:journaliste|reporter|correspondant|correspondante|r[eé]dacteur|r[eé]dactrice)\s+(?:rapporte|a rapport[eé]|dit|a dit|[eé]crit|a [eé]crit|affirme|a affirm[eé])\b",
        r"\bselon\s+(?:un|une)?\s*(?:journaliste|reporter|correspondant|correspondante)\b",
        r"\ba dit aux\s+(?:journalistes|reporters)\b",
        r"\ba parl[eé] aux\s+(?:journalistes|reporters)\b|\ba parl[eé] [aà] la presse\b",
        r"\brapports? de presse\b",
        r"\bconf[eé]rence de presse\b",
        r"\bcommuniqu[eé] de presse\b",
    ],
    retrospective_patterns=[
        r"\b(?:\d+|un|une)\s+(?:ans?|mois)\s+(?:plus tard|apr[eè]s)\b",
        r"\banniversaire\b",
        r"\ben souvenir\b|\bun an apr[eè]s\b",
        r"\bce jour-l[àa]\b",
    ],
    negation_prefixes=[r"\bpas", r"\bjamais", r"\bplus"],
    extra_negatable_actions=["endommag[eé]", "endommag[eé]e", "bless[eé]", "bless[eé]e"],
)


RUSSIAN = LanguageTerms(
    media_subject_terms=[
        "журналист", "журналистка", "журналисты", "журналистки",
        "репортёр", "репортер", "репортёры", "репортеры",
        "корреспондент", "корреспондентка", "корреспонденты",
        "военный корреспондент",
        "фотожурналист", "фотожурналисты",
        "оператор", "операторы",
        "редактор", "редакторы",
        "обозреватель", "обозреватели",
        "диктор", "дикторы",
        "сотрудник СМИ", "сотрудники СМИ",
        "съёмочная группа", "съемочная группа",
        "газета",
        "редакция",
        "СМИ", "издание",
        "радиостанция",
        "телеканал", "телестанция",
        "студент журналистики", "студентка журналистики",
    ],
    action_terms_by_type={
        "KILLING": [
            "убит", "убита", "убиты",
            "застрелен", "застрелена",
            "зарезан", "зарезана",
            "забит до смерти", "забита до смерти",
            "найден мёртвым", "найдена мёртвой",
            "найден мертвым", "найдена мертвой",
            "застрелен насмерть", "застрелена насмерть",
        ],
        "DETENTION": [
            "задержан", "задержана", "задержаны",
            "арестован", "арестована", "арестованы",
            "заключён в тюрьму", "заключена в тюрьму",
            "приговорён", "приговорена",
            "под стражей",
        ],
        "ATTACK": [
            "атакован", "атакована",
            "избит", "избита",
            "ранен", "ранена",
            "похищен", "похищена",
            "подвергся пыткам", "подверглась пыткам",
        ],
        "THREAT": [
            "угрожали", "угрожал", "угрожала",
            "угроза убийством", "угрозы убийством",
            "преследовали", "преследовал", "преследовала",
            "запугивали", "запугивал", "запугивала",
        ],
        "CENSORSHIP": [
            "подвергся цензуре", "подверглась цензуре",
            "запрещён", "запрещена",
            "заблокирован", "заблокирована",
            "закрыт", "закрыта",
            "приостановлен", "приостановлена",
            "обыскан", "обыскана",
        ],
        "DISAPPEARANCE": [
            "пропал без вести", "пропала без вести",
            "насильственно исчез", "насильственно исчезла",
        ],
    },
    source_attribution_patterns=[
        r"\b(?:журналист\w*|репортёр\w*|репортер\w*|корреспондент\w*|редактор\w*)\s+(?:сообщ\w+|заяв\w+|расска\w+|пиш\w+|написал\w*)\b",
        r"\bпо словам\s+(?:журналиста|репортёра|репортера|корреспондента)\b",
        r"\bсказал\w*\s+журналистам\b|\bсообщил\w*\s+журналистам\b",
        r"\bсообщил\w*\s+прессе\b|\bпоговорил\w*\s+с\s+журналистами\b",
        r"\bсообщения СМИ\b",
        r"\bпресс-конференци\w+\b",
        r"\bпресс-релиз\b",
    ],
    retrospective_patterns=[
        r"\b(?:\d+|один|одна)\s+(?:год|года|лет|месяц\w*)\s+(?:спустя|назад|после)\b",
        r"\bгодовщина\b",
        r"\bвспомина\w+\b",
        r"\bв этот день\b",
    ],
    negation_prefixes=[r"\bне", r"\bникогда"],
    extra_negatable_actions=["повреждён", "повреждена", "пострадал", "пострадала"],
)


LANGUAGE_TERMS: Dict[str, LanguageTerms] = {
    "es": SPANISH,
    "pt": PORTUGUESE,
    "it": ITALIAN,
    "fr": FRENCH,
    "ru": RUSSIAN,
}

# Full language names, in case metadata ever carries them instead of an
# ISO 639-1 code (older GDELT-style fixtures used e.g. "Spanish").
LANGUAGE_ALIASES: Dict[str, str] = {
    "spanish": "es",
    "portuguese": "pt",
    "italian": "it",
    "french": "fr",
    "russian": "ru",
}
