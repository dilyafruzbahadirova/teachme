from django import forms

from .models import Flashcard


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


class FlashcardForm(forms.ModelForm):
    class Meta:
        model = Flashcard
        fields = ['question', 'answer', 'source_quote']
        labels = {
            'question': 'Сұрақ',
            'answer': 'Жауап',
            'source_quote': 'Дәйексөз',
        }

    def clean_source_quote(self):
        quote = self.cleaned_data['source_quote']
        quote = quote.replace('\r\n', '\n').replace('\r', '\n')

        source = self.instance.source
        source_text = source.text.replace('\r\n', '\n').replace('\r', '\n')

        if quote not in source_text:
            raise forms.ValidationError(
                'Дәйексөз бастапқы мәтінде дәл осылай кездесуі керек. '
                'Мәтінді бастапқы мәтіннен өзгертпей көшіріңіз.'
            )

        return quote