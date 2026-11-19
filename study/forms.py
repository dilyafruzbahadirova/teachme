from django import forms


class SourceForm(forms.Form):
    title = forms.CharField(
        max_length=120,
        strip=True,
        label='Тақырып',
    )

    text = forms.CharField(
        min_length=80,
        max_length=12000,
        strip=True,
        widget=forms.Textarea,
        label='Оқу мәтіні',
    )

    def clean_text(self):
        text = self.cleaned_data['text']
        return text.replace('\r\n', '\n').replace('\r', '\n')