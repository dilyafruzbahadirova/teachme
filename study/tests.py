import json
from copy import deepcopy
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse

from .demo import DEMO_TEXT, DEMO_CARDS
from .models import Source, Flashcard
from .services import GenerationError


class StudyFlowTests(TestCase):
    def setUp(self):
        self.home_url = reverse('home')
        self.valid_data = {
            'title': 'Тест материалы',
            'text': DEMO_TEXT,
        }

    @override_settings(TEACHME_MODE='demo')
    def test_valid_demo_post_saves_source_and_three_cards(self):
        response = self.client.post(self.home_url, self.valid_data)

        self.assertEqual(response.status_code, 302)

        source = Source.objects.get()
        self.assertRedirects(
            response,
            reverse('source_detail', kwargs={'pk': source.pk}),
        )

        self.assertEqual(Source.objects.count(), 1)
        self.assertEqual(Flashcard.objects.count(), 3)
        self.assertEqual(source.generation_mode, 'demo')

    @override_settings(TEACHME_MODE='demo')
    def test_short_text_does_not_call_provider(self):
        data = {
            'title': 'Қысқа мәтін',
            'text': 'Бұл өте қысқа мәтін.',
        }

        with patch('study.views.generate_cards') as generate_mock:
            response = self.client.post(self.home_url, data)

        self.assertEqual(response.status_code, 200)
        generate_mock.assert_not_called()
        self.assertEqual(Source.objects.count(), 0)
        self.assertEqual(Flashcard.objects.count(), 0)
        self.assertTrue(response.context['form'].is_bound)

    @override_settings(
        TEACHME_MODE='live',
        GEMINI_API_KEY='test-api-key',
        GEMINI_MODEL='test-model',
    )
    def test_invalid_source_quote_rejects_all_cards(self):
        invalid_cards = deepcopy(DEMO_CARDS)
        invalid_cards[1]['source_quote'] = (
            'Бұл дәйексөз бастапқы мәтінде жоқ.'
        )

        generated_text = json.dumps(
            {'cards': invalid_cards},
            ensure_ascii=False,
        )

        provider_response = MagicMock()
        provider_response.read.return_value = json.dumps({
            'candidates': [
                {
                    'content': {
                        'parts': [
                            {'text': generated_text},
                        ],
                    },
                },
            ],
        }).encode('utf-8')

        response_context = MagicMock()
        response_context.__enter__.return_value = provider_response

        with patch(
            'study.services.urlopen',
            return_value=response_context,
        ) as urlopen_mock:
            response = self.client.post(
                self.home_url,
                {
                    'title': 'Қате дәйексөз',
                    'text': DEMO_TEXT,
                },
            )

        urlopen_mock.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].is_bound)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(Source.objects.count(), 0)
        self.assertEqual(Flashcard.objects.count(), 0)

    @override_settings(
        TEACHME_MODE='live',
        GEMINI_API_KEY='test-api-key',
        GEMINI_MODEL='test-model',
    )
    def test_provider_generation_error_keeps_bound_form_and_saves_nothing(self):
        with patch(
            'study.services.urlopen',
            side_effect=URLError('network unavailable'),
        ) as urlopen_mock:
            response = self.client.post(
                self.home_url,
                {
                    'title': 'Provider қатесі',
                    'text': DEMO_TEXT,
                },
            )

        urlopen_mock.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].is_bound)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(Source.objects.count(), 0)
        self.assertEqual(Flashcard.objects.count(), 0)

    @override_settings(TEACHME_MODE='demo')
    def test_database_error_on_second_card_rolls_back_everything(self):
        original_create = Flashcard.objects.create
        call_count = 0

        def create_with_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                return original_create(*args, **kwargs)

            if call_count == 2:
                raise DatabaseError('Test database error')

            return original_create(*args, **kwargs)

        with patch(
            'study.views.Flashcard.objects.create',
            side_effect=create_with_failure,
        ):
            response = self.client.post(
                self.home_url,
                self.valid_data,
            )

        self.assertEqual(call_count, 2)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].is_bound)
        self.assertTrue(response.context['form'].non_field_errors())

        self.assertEqual(Source.objects.count(), 0)
        self.assertEqual(Flashcard.objects.count(), 0)

    @override_settings(TEACHME_MODE='demo')
    def test_two_detail_gets_do_not_call_provider_or_change_database(self):
        source = Source.objects.create(
            title='GET тесті',
            text=DEMO_TEXT,
            generation_mode='demo',
        )

        for position, card in enumerate(DEMO_CARDS, 1):
            Flashcard.objects.create(
                source=source,
                position=position,
                question=card['question'],
                answer=card['answer'],
                source_quote=card['source_quote'],
            )

        source_count_before = Source.objects.count()
        card_count_before = Flashcard.objects.count()

        detail_url = reverse(
            'source_detail',
            kwargs={'pk': source.pk},
        )

        with patch('study.views.generate_cards') as generate_mock:
            first_response = self.client.get(detail_url)
            second_response = self.client.get(detail_url)

        generate_mock.assert_not_called()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        self.assertEqual(Source.objects.count(), source_count_before)
        self.assertEqual(Flashcard.objects.count(), card_count_before)