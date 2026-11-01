# Populate British IPA for rows created before the accent toggle existed.

from django.db import migrations


def backfill_ipa_uk(apps, schema_editor):
    from services.pronunciation import ipa_for_word, normalize_word

    WordToken = apps.get_model("diaries", "WordToken")
    WordLookup = apps.get_model("diaries", "WordLookup")
    database = schema_editor.connection.alias

    for token in WordToken.objects.using(database).filter(ipa_uk="").iterator():
        ipa_uk = ipa_for_word(normalize_word(token.surface), "uk") or ""
        if ipa_uk:
            WordToken.objects.using(database).filter(pk=token.pk).update(
                ipa_uk=ipa_uk
            )

    for lookup in WordLookup.objects.using(database).filter(ipa_uk="").iterator():
        ipa_uk = ipa_for_word(lookup.word, "uk") or ""
        if ipa_uk:
            WordLookup.objects.using(database).filter(pk=lookup.pk).update(
                ipa_uk=ipa_uk
            )


class Migration(migrations.Migration):

    dependencies = [
        ("diaries", "0010_remove_diaryreadaloud_diaries_unique_version_read_aloud_speed_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_ipa_uk, migrations.RunPython.noop),
    ]
