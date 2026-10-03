"""Automatic translation of player-written text between the site's two languages.

Text saved while the site is in one language is translated into the other by a background
worker (`management/commands/translate_worker.py`), so a player reading in the other language
sees it in theirs. This module is the web side: queue a job when text changes
(`enqueue`), and look up what to show (`translated`, `search_text`). The worker side - the
only code holding the LLM credentials - is `llm.py`.
"""

from django.conf import settings
from django.utils.translation import get_language

from apps.frontend.models import TranslationJob

#: What a job may carry: bounds what a compromised web process could make the worker send on.
MAX_FIELD_CHARS = 8000
MAX_JOB_CHARS = 20000
#: Queue length past which new jobs are dropped (the original text is simply shown untranslated).
MAX_PENDING = 200


def _site_languages() -> list[str]:
    return [code for code, _name in settings.LANGUAGES]


def current_language() -> str:
    """The active site language code ("en"/"it"), whatever variant the request negotiated."""
    return (get_language() or settings.LANGUAGE_CODE).split("-")[0]


def enqueue(kind: str, object_id: int, fields: dict[str, str], source_lang: str | None = None):
    """Queue `fields` ({name: text}) of one object for translation into the other language.
    Empty texts are skipped, and so is everything when there is nothing to translate or no
    other language. A still-waiting job for the same object is replaced by this newer one."""
    source_lang = source_lang or current_language()
    languages = _site_languages()
    fields = {
        name: text[:MAX_FIELD_CHARS]
        for name, text in fields.items()
        if isinstance(text, str) and text.strip()
    }
    if source_lang not in languages or len(languages) != 2 or not fields:
        return None
    if sum(len(text) for text in fields.values()) > MAX_JOB_CHARS:
        return None
    pending = TranslationJob.objects.filter(status=TranslationJob.PENDING)
    if pending.count() + 2 > MAX_PENDING:
        return None
    pending.filter(kind=kind, object_id=object_id).delete()
    # One job per language: the active language is where the text was most likely written, but
    # not surely (an Italian text typed while reading English), so each job asks for its target
    # language and the model hands back text already in it unchanged.
    jobs = [
        TranslationJob.objects.create(
            kind=kind,
            object_id=object_id,
            source_lang=next(lang for lang in languages if lang != target),
            target_lang=target,
            source=fields,
        )
        for target in sorted(languages, key=lambda lang: lang == source_lang)  # main job first
    ]
    return jobs[0]


def _latest_done(kind: str, object_ids, target_lang: str) -> dict[int, TranslationJob]:
    """The newest finished job per object that translated into `target_lang`."""
    latest: dict[int, TranslationJob] = {}
    jobs = TranslationJob.objects.filter(
        kind=kind,
        object_id__in=list(object_ids),
        target_lang=target_lang,
        status=TranslationJob.DONE,
    ).order_by("-id")
    for job in jobs:
        latest.setdefault(job.object_id, job)
    return latest


def translated_texts(kind: str, objects: dict[int, dict[str, str]], lang: str | None = None):
    """For each object id, `{field: (text, was_translated)}` in language `lang` (default: the
    active one). A field shows its translation only if a finished job translated into `lang`
    from exactly the field's current text; anything else falls back to the text as written."""
    lang = lang or current_language()
    jobs = _latest_done(kind, objects, lang)
    shown = {}
    for object_id, fields in objects.items():
        job = jobs.get(object_id)
        shown[object_id] = {}
        for name, text in fields.items():
            done = (
                job.result[name]
                if job
                and isinstance(job.result, dict)
                and isinstance(job.result.get(name), str)
                and job.source.get(name) == text[:MAX_FIELD_CHARS]
                else None
            )
            shown[object_id][name] = (done, True) if done and done != text else (text, False)
    return shown


def search_text(kind: str, objects: dict[int, dict[str, str]]) -> dict[int, str]:
    """Every text a search should look in for each object: the originals plus the translations
    that are still current, in any language - so a word is found whichever language it was
    written or is being read in."""
    haystack = {object_id: list(fields.values()) for object_id, fields in objects.items()}
    for lang in _site_languages():
        for object_id, fields in translated_texts(kind, objects, lang).items():
            haystack[object_id] += [
                text for text, was_translated in fields.values() if was_translated
            ]
    return {object_id: "\n".join(texts) for object_id, texts in haystack.items()}
