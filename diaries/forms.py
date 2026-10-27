"""Forms for diary text, English versions, and IPA corrections."""

from django import forms

from services.pronunciation import MAX_IPA_LENGTH, clean_manual_ipa

from .models import DiaryEntry

MAX_DIARY_CHARS = 5000
MAX_ENGLISH_CHARS = 5000


class DiaryForm(forms.ModelForm):
    class Meta:
        model = DiaryEntry
        fields = ["entry_date", "title", "chinese_text"]
        labels = {
            "entry_date": "日记日期",
            "title": "标题（可选）",
            "chinese_text": "中文日记",
        }
        widgets = {
            "entry_date": forms.DateInput(attrs={"type": "date"}),
            "title": forms.TextInput(
                attrs={"placeholder": "不填也可以", "maxlength": 100}
            ),
            "chinese_text": forms.Textarea(
                attrs={
                    "rows": 12,
                    "maxlength": MAX_DIARY_CHARS,
                    "placeholder": "写下今天想练习的内容……",
                }
            ),
        }

    def clean_chinese_text(self) -> str:
        value = (self.cleaned_data.get("chinese_text") or "").strip()
        if not value:
            raise forms.ValidationError("请先写一点中文日记。")
        if len(value) > MAX_DIARY_CHARS:
            raise forms.ValidationError(
                f"中文日记不能超过 {MAX_DIARY_CHARS} 个字符。"
            )
        return value

    def clean_title(self) -> str:
        return (self.cleaned_data.get("title") or "").strip()


class EnglishVersionForm(forms.Form):
    english_text = forms.CharField(
        label="英文内容",
        max_length=MAX_ENGLISH_CHARS,
        widget=forms.Textarea(
            attrs={
                "rows": 12,
                "maxlength": MAX_ENGLISH_CHARS,
                "placeholder": "每行写一句完整英文。",
            }
        ),
        help_text="建议每行一句。保存后会重新生成句子和美式音标。",
    )

    def clean_english_text(self) -> str:
        value = (self.cleaned_data.get("english_text") or "").strip()
        if not value:
            raise forms.ValidationError("英文内容不能为空。")
        if len(value) > MAX_ENGLISH_CHARS:
            raise forms.ValidationError(
                f"英文内容不能超过 {MAX_ENGLISH_CHARS} 个字符。"
            )
        return value


class IpaCorrectionForm(forms.Form):
    """Dynamically create one IPA input per token on a sentence."""

    def __init__(self, *args, tokens=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.tokens = list(tokens)
        self.token_fields = []
        for token in self.tokens:
            field_name = f"ipa_{token.pk.hex}"
            self.token_fields.append((token, field_name))
            self.fields[field_name] = forms.CharField(
                required=False,
                initial=token.ipa,
                max_length=MAX_IPA_LENGTH,
                label=token.surface,
                widget=forms.TextInput(
                    attrs={
                        "class": "ipa-input",
                        "autocomplete": "off",
                        "spellcheck": "false",
                        "aria-label": f"{token.surface} 的音标",
                    }
                ),
            )

    def clean(self):
        cleaned_data = super().clean()
        for token, field_name in self.token_fields:
            if field_name not in cleaned_data:
                continue
            try:
                cleaned_data[field_name] = clean_manual_ipa(
                    cleaned_data.get(field_name, "")
                )
            except ValueError as exc:
                self.add_error(field_name, str(exc))
        return cleaned_data

    def corrections(self):
        """Yield (token, cleaned_ipa_or_empty) for valid forms."""
        for token, field_name in self.token_fields:
            yield token, self.cleaned_data.get(field_name, "")
