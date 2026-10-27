"""URL routes for private diary content."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.diary_list, name="diary_list"),
    path("new/", views.diary_create, name="diary_create"),
    path("<uuid:diary_id>/", views.diary_detail, name="diary_detail"),
    path("<uuid:diary_id>/edit/", views.diary_edit, name="diary_edit"),
    path("<uuid:diary_id>/translate/", views.diary_translate, name="diary_translate"),
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
        "words/<uuid:token_id>/assess/",
        views.assess_word,
        name="assess_word",
    ),
    path("audio/<uuid:asset_id>/", views.serve_audio_asset, name="serve_audio_asset"),
]
