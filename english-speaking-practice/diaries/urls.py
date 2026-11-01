"""URL routes for private diary content."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.diary_list, name="diary_list"),
    path("new/", views.diary_create, name="diary_create"),
    path("ocr/", views.ocr_upload, name="ocr_upload"),
    path("<uuid:diary_id>/", views.diary_detail, name="diary_detail"),
    path("<uuid:diary_id>/edit/", views.diary_edit, name="diary_edit"),
    path("<uuid:diary_id>/translate/", views.diary_translate, name="diary_translate"),
    path(
        "<uuid:diary_id>/read-aloud/",
        views.diary_read_aloud,
        name="diary_read_aloud",
    ),
    path(
        "<uuid:diary_id>/english/",
        views.diary_edit_english,
        name="diary_edit_english",
    ),
    path("<uuid:diary_id>/delete/", views.diary_delete, name="diary_delete"),
    path(
        "sentences/<uuid:sentence_id>/ipa/",
        views.edit_sentence_ipa,
        name="edit_sentence_ipa",
    ),
    path(
        "sentences/<uuid:sentence_id>/tts/<str:speed>/",
        views.generate_sentence_tts,
        name="sentence_tts",
    ),
    path(
        "sentences/<uuid:sentence_id>/recordings/",
        views.upload_recording,
        name="upload_recording",
    ),
    path(
        "recordings/<uuid:recording_id>/delete/",
        views.delete_recording,
        name="delete_recording",
    ),
    path("words/", views.word_lookup, name="word_lookup"),
    path(
        "words/lookup/<uuid:lookup_id>/phonics/",
        views.lookup_phonics,
        name="lookup_phonics",
    ),
    path(
        "words/lookup/<uuid:lookup_id>/phonics/<str:mode>/",
        views.lookup_phonics_audio,
        name="lookup_phonics_audio",
    ),
    path(
        "words/lookup/<uuid:lookup_id>/tts/",
        views.lookup_tts,
        name="lookup_tts",
    ),
    path(
        "words/lookup/<uuid:lookup_id>/assess/",
        views.assess_lookup,
        name="assess_lookup",
    ),
    path(
        "words/<uuid:token_id>/phonics/",
        views.word_phonics,
        name="word_phonics",
    ),
    path(
        "words/<uuid:token_id>/phonics/<str:mode>/",
        views.word_phonics_audio,
        name="word_phonics_audio",
    ),
    path(
        "words/<uuid:token_id>/tts/",
        views.word_tts,
        name="word_tts",
    ),
    path(
        "words/<uuid:token_id>/assess/",
        views.assess_word,
        name="assess_word",
    ),
    path("audio/<uuid:asset_id>/", views.serve_audio_asset, name="serve_audio_asset"),
]
