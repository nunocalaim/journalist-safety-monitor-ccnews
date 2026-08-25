import pytest

from language_detect import detect_language


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        ("en", "The journalist was killed by armed men in the city, according to local witnesses. Police are investigating the case as a possible targeted attack on the press."),
        ("es", "El periodista fue asesinado por hombres armados en la ciudad, segun informaron testigos locales. La policia investiga el caso como un posible ataque dirigido contra la prensa."),
        ("ru", "Журналист был убит вооруженными людьми в городе, сообщили местные свидетели. Полиция расследует этот случай как возможное нападение на прессу."),
        ("pt", "O jornalista foi morto por homens armados na cidade, segundo testemunhas locais. A policia investiga o caso como um possivel ataque direcionado contra a imprensa."),
        ("ar", "قُتل الصحفي على يد مسلحين في المدينة، وفقا لما أفاد به شهود محليون. وتحقق الشرطة في القضية باعتبارها هجوما محتملا يستهدف الصحافة."),
        ("it", "Il giornalista è stato ucciso da uomini armati nella città, secondo testimoni locali. La polizia sta indagando sul caso come possibile attacco mirato alla stampa."),
        ("fr", "Le journaliste a été tué par des hommes armés dans la ville, selon des témoins locaux. La police enquête sur cette affaire comme une possible attaque ciblée contre la presse."),
        ("fa", "خبرنگار توسط افراد مسلح در شهر کشته شد، به گفته شاهدان محلی. پلیس این پرونده را به عنوان یک حمله احتمالی هدفمند علیه مطبوعات بررسی می کند."),
    ],
)
def test_detect_language_identifies_active_source_languages(expected, text):
    assert detect_language(text) == expected


def test_detect_language_empty_string_for_missing_text():
    assert detect_language("") == ""
    assert detect_language(None) == ""


def test_detect_language_empty_string_for_text_too_short_to_classify_reliably():
    assert detect_language("Reuters") == ""
