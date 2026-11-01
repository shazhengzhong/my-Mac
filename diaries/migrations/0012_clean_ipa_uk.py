# Strip the newline that the first Britfone loader left on IPA values.

from django.db import migrations


def clean_ipa_uk(apps, schema_editor):
    WordToken = apps.get_model("diaries", "WordToken")
    WordLookup = apps.get_model("diaries", "WordLookup")
    database = schema_editor.connection.alias

    for token in WordToken.objects.using(database).exclude(ipa_uk="").iterator():
        cleaned = token.ipa_uk.strip()
        if cleaned != token.ipa_uk:
            WordToken.objects.using(database).filter(pk=token.pk).update(
                ipa_uk=cleaned
            )

    for lookup in WordLookup.objects.using(database).exclude(ipa_uk="").iterator():
        cleaned = lookup.ipa_uk.strip()
        if cleaned != lookup.ipa_uk:
            WordLookup.objects.using(database).filter(pk=lookup.pk).update(
                ipa_uk=cleaned
            )


class Migration(migrations.Migration):

    dependencies = [
        ("diaries", "0011_backfill_ipa_uk"),
    ]

    operations = [
        migrations.RunPython(clean_ipa_uk, migrations.RunPython.noop),
    ]
