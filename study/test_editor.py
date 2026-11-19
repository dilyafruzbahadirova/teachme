from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from .demo import DEMO_CARDS, DEMO_TEXT
from .models import Flashcard, Source

MISSING_PK = 999999


class EditorTestCase(TestCase):
    """Негізгі класс: generate_cards шақырылмауын қадағалайды."""

    def setUp(self):
        patcher = patch('study.views.generate_cards')
        self.generate_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.generate_mock.assert_not_called()
        super().tearDown()

    # ---------- көмекшілер ----------

    def make_source(self, title='Жинақ', text=DEMO_TEXT, verified=()):
        """verified: тексерілген карточкалардың position мәндері (1-ден)."""
        source = Source.objects.create(
            title=title,
            text=text,
            generation_mode='demo',
        )
        cards = []
        for position, data in enumerate(DEMO_CARDS, 1):
            cards.append(Flashcard.objects.create(
                source=source,
                position=position,
                question=data['question'],
                answer=data['answer'],
                source_quote=data['source_quote'],
                is_verified=position in verified,
            ))
        return source, cards

    def cards_snapshot(self):
        return list(Flashcard.objects.order_by('pk').values_list(
            'pk', 'source_id', 'position', 'question',
            'answer', 'source_quote', 'is_verified',
        ))

    def sources_snapshot(self):
        return list(Source.objects.order_by('pk').values_list(
            'pk', 'title', 'text', 'generation_mode',
        ))

    def assert_db_unchanged(self, cards_before, sources_before):
        self.assertEqual(self.cards_snapshot(), cards_before)
        self.assertEqual(self.sources_snapshot(), sources_before)

    @staticmethod
    def detail_url(source_or_pk):
        pk = getattr(source_or_pk, 'pk', source_or_pk)
        return reverse('source_detail', kwargs={'pk': pk})

    @staticmethod
    def edit_url(card_or_pk):
        pk = getattr(card_or_pk, 'pk', card_or_pk)
        return reverse('card_edit', kwargs={'pk': pk})

    @staticmethod
    def delete_url(card_or_pk):
        pk = getattr(card_or_pk, 'pk', card_or_pk)
        return reverse('card_delete', kwargs={'pk': pk})

    @staticmethod
    def review_url(card_or_pk):
        pk = getattr(card_or_pk, 'pk', card_or_pk)
        return reverse('card_review', kwargs={'pk': pk})

    @staticmethod
    def valid_edit_data():
        return {
            'question': 'Жаңа сұрақ?',
            'answer': 'Жаңа жауап.',
            'source_quote': DEMO_CARDS[0]['source_quote'],
        }


class CardEditGetTests(EditorTestCase):
    def test_get_shows_form_with_card_data_and_writes_nothing(self):
        source, cards = self.make_source(verified=(1,))
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        response = self.client.get(self.edit_url(cards[0]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'study/card_form.html')
        self.assertFalse(response.context['form'].is_bound)
        self.assertEqual(
            response.context['form'].instance.pk,
            cards[0].pk,
        )
        self.assertContains(response, cards[0].question)
        self.assert_db_unchanged(cards_before, sources_before)

        cards[0].refresh_from_db()
        self.assertTrue(cards[0].is_verified)

    def test_form_has_only_three_editable_fields(self):
        source, cards = self.make_source()

        response = self.client.get(self.edit_url(cards[0]))

        self.assertEqual(
            list(response.context['form'].fields),
            ['question', 'answer', 'source_quote'],
        )


class CardEditPostTests(EditorTestCase):
    def test_valid_post_changes_only_this_card_and_resets_verification(self):
        source, cards = self.make_source(verified=(1, 2))
        neighbor_before = list(
            Flashcard.objects.filter(pk=cards[1].pk).values()
        )
        data = self.valid_edit_data()

        response = self.client.post(self.edit_url(cards[0]), data)

        self.assertRedirects(response, self.detail_url(source))

        cards[0].refresh_from_db()
        self.assertEqual(cards[0].question, data['question'])
        self.assertEqual(cards[0].answer, data['answer'])
        self.assertEqual(cards[0].source_quote, data['source_quote'])
        self.assertFalse(cards[0].is_verified)
        self.assertEqual(cards[0].source_id, source.pk)
        self.assertEqual(cards[0].position, 1)

        # көрші карточка өзгермеген, тексерілген күйі қалған
        self.assertEqual(
            list(Flashcard.objects.filter(pk=cards[1].pk).values()),
            neighbor_before,
        )
        self.assertTrue(
            Flashcard.objects.get(pk=cards[1].pk).is_verified
        )

    def test_valid_post_on_unverified_card_stays_unverified(self):
        source, cards = self.make_source()

        response = self.client.post(
            self.edit_url(cards[0]),
            self.valid_edit_data(),
        )

        self.assertEqual(response.status_code, 302)
        cards[0].refresh_from_db()
        self.assertFalse(cards[0].is_verified)

    def test_invalid_posts_show_errors_and_write_nothing(self):
        source, cards = self.make_source(verified=(1,))
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        cases = {
            'бос сұрақ': ('question', {'question': ''}),
            'бос жауап': ('answer', {'answer': ''}),
            'бос дәйексөз': ('source_quote', {'source_quote': ''}),
            'ұзын сұрақ': ('question', {'question': 'в' * 301}),
            'ұзын жауап': ('answer', {'answer': 'а' * 1601}),
            'конспектте жоқ дәйексөз': (
                'source_quote',
                {'source_quote': 'Бұл дәйексөз конспектте жоқ.'},
            ),
        }

        for name, (field, override) in cases.items():
            with self.subTest(name):
                data = self.valid_edit_data()
                data.update(override)

                response = self.client.post(self.edit_url(cards[0]), data)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'study/card_form.html')
                form = response.context['form']
                self.assertTrue(form.is_bound)
                self.assertIn(field, form.errors)
                self.assert_db_unchanged(cards_before, sources_before)

    def test_invalid_quote_keeps_entered_data_and_shows_message(self):
        source, cards = self.make_source()
        data = self.valid_edit_data()
        data['source_quote'] = 'Бұл дәйексөз конспектте жоқ.'

        response = self.client.post(self.edit_url(cards[0]), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Бұл дәйексөз конспектте жоқ.')
        self.assertContains(response, data['question'])
        self.assertContains(
            response,
            'Дәйексөз бастапқы мәтінде дәл осылай кездесуі керек',
        )

    def test_quote_from_another_source_is_rejected(self):
        source_a, cards_a = self.make_source(
            title='A',
            text='Бірінші жинақтың жеке мәтіні осында жазылған.',
        )
        source_b, cards_b = self.make_source(title='B')
        cards_before = self.cards_snapshot()
        data = self.valid_edit_data()
        data['source_quote'] = DEMO_CARDS[0]['source_quote']

        response = self.client.post(self.edit_url(cards_a[0]), data)

        self.assertEqual(response.status_code, 200)
        self.assertIn('source_quote', response.context['form'].errors)
        self.assertEqual(self.cards_snapshot(), cards_before)

    def test_crlf_quote_is_normalized_and_matches_source(self):
        source, cards = self.make_source()
        data = self.valid_edit_data()
        data['source_quote'] = (
            'устройства, которые обмениваются данными.\r\n'
            'IP-адрес — это адрес устройства в IP-сети;'
        )

        response = self.client.post(self.edit_url(cards[0]), data)

        self.assertEqual(response.status_code, 302)
        cards[0].refresh_from_db()
        self.assertNotIn('\r', cards[0].source_quote)
        self.assertIn(
            'данными.\nIP-адрес',
            cards[0].source_quote,
        )

    def test_quote_matches_source_stored_with_crlf(self):
        source, cards = self.make_source(
            text=DEMO_TEXT.replace('\n', '\r\n'),
        )
        data = self.valid_edit_data()
        data['source_quote'] = (
            'обмениваются данными.\nIP-адрес — это адрес устройства'
        )

        response = self.client.post(self.edit_url(cards[0]), data)

        self.assertEqual(response.status_code, 302)

    def test_fake_source_position_and_is_verified_are_ignored(self):
        source, cards = self.make_source(verified=(1,))
        other_source, other_cards = self.make_source(title='Басқа')
        data = self.valid_edit_data()
        data.update({
            'source': other_source.pk,
            'position': 99,
            'is_verified': 'on',
            'id': other_cards[0].pk,
        })

        response = self.client.post(self.edit_url(cards[0]), data)

        self.assertEqual(response.status_code, 302)
        cards[0].refresh_from_db()
        self.assertEqual(cards[0].source_id, source.pk)
        self.assertEqual(cards[0].position, 1)
        self.assertFalse(cards[0].is_verified)
        self.assertEqual(cards[0].question, data['question'])

        # басқа Source-тың карточкасы өзгермеген
        other_cards[0].refresh_from_db()
        self.assertEqual(other_cards[0].question, DEMO_CARDS[0]['question'])
        self.assertEqual(other_cards[0].source_id, other_source.pk)

    def test_fake_is_verified_cannot_keep_card_verified(self):
        source, cards = self.make_source(verified=(1,))
        data = self.valid_edit_data()
        data['is_verified'] = 'True'

        self.client.post(self.edit_url(cards[0]), data)

        cards[0].refresh_from_db()
        self.assertFalse(cards[0].is_verified)

    def test_database_error_on_save_shows_error_and_writes_nothing(self):
        source, cards = self.make_source(verified=(1,))
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        with patch.object(
            Flashcard,
            'save',
            side_effect=DatabaseError('Test database error'),
        ):
            response = self.client.post(
                self.edit_url(cards[0]),
                self.valid_edit_data(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assert_db_unchanged(cards_before, sources_before)


class CardDeleteTests(EditorTestCase):
    def test_get_shows_confirmation_and_does_not_delete(self):
        source, cards = self.make_source()
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        response = self.client.get(self.delete_url(cards[0]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'study/card_confirm_delete.html',
        )
        self.assertContains(response, cards[0].question)
        self.assertContains(response, 'Иә, өшіру')
        self.assertContains(response, self.detail_url(source))
        self.assert_db_unchanged(cards_before, sources_before)

    def test_cancel_link_leads_to_source_and_deletes_nothing(self):
        source, cards = self.make_source()
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        confirm = self.client.get(self.delete_url(cards[0]))
        self.assertContains(confirm, self.detail_url(source))

        response = self.client.get(self.detail_url(source))

        self.assertEqual(response.status_code, 200)
        self.assert_db_unchanged(cards_before, sources_before)

    def test_post_deletes_only_one_card(self):
        source, cards = self.make_source()
        other_source, other_cards = self.make_source(title='Басқа')
        other_cards_before = list(
            Flashcard.objects.filter(source=other_source)
            .order_by('pk')
            .values()
        )
        first_before = list(
            Flashcard.objects.filter(pk=cards[0].pk).values()
        )
        third_before = list(
            Flashcard.objects.filter(pk=cards[2].pk).values()
        )

        response = self.client.post(self.delete_url(cards[1]))

        self.assertRedirects(response, self.detail_url(source))

        self.assertFalse(Flashcard.objects.filter(pk=cards[1].pk).exists())
        self.assertTrue(Source.objects.filter(pk=source.pk).exists())
        self.assertTrue(Source.objects.filter(pk=other_source.pk).exists())
        self.assertEqual(Flashcard.objects.filter(source=source).count(), 2)

        # көршілер өзгермеген
        self.assertEqual(
            list(Flashcard.objects.filter(pk=cards[0].pk).values()),
            first_before,
        )
        self.assertEqual(
            list(Flashcard.objects.filter(pk=cards[2].pk).values()),
            third_before,
        )

        # басқа Source карточкалары өзгермеген
        self.assertEqual(
            list(
                Flashcard.objects.filter(source=other_source)
                .order_by('pk')
                .values()
            ),
            other_cards_before,
        )

    def test_positions_are_not_renumbered_after_delete(self):
        source, cards = self.make_source()

        self.client.post(self.delete_url(cards[1]))

        positions = list(
            Flashcard.objects.filter(source=source)
            .order_by('position')
            .values_list('position', flat=True)
        )
        self.assertEqual(positions, [1, 3])

    def test_detail_counts_are_recomputed_after_delete(self):
        source, cards = self.make_source(verified=(1,))

        self.client.post(self.delete_url(cards[0]))
        response = self.client.get(self.detail_url(source))

        self.assertEqual(response.context['total_count'], 2)
        self.assertEqual(response.context['verified_count'], 0)
        self.assertEqual(response.context['pending_count'], 2)
        self.assertContains(response, 'Тексерілді 0 / 2')
        self.assertContains(response, 'Қалды 2')

    def test_deleting_last_card_shows_message_and_source_text(self):
        source, cards = self.make_source()

        for card in cards:
            self.client.post(self.delete_url(card))

        self.assertEqual(Flashcard.objects.filter(source=source).count(), 0)
        self.assertTrue(Source.objects.filter(pk=source.pk).exists())

        response = self.client.get(self.detail_url(source))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 0)
        self.assertContains(response, 'карточкалар қалмады')
        self.assertContains(
            response,
            'Компьютерная сеть — это соединённые устройства',
        )
        self.assertContains(response, '<details open>')

    def test_database_error_on_delete_shows_error_and_keeps_card(self):
        source, cards = self.make_source()
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        with patch.object(
            Flashcard,
            'delete',
            side_effect=DatabaseError('Test database error'),
        ):
            response = self.client.post(self.delete_url(cards[0]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['error'])
        self.assert_db_unchanged(cards_before, sources_before)


class CardReviewTests(EditorTestCase):
    def test_get_returns_405_and_writes_nothing(self):
        source, cards = self.make_source(verified=(1,))
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        response = self.client.get(self.review_url(cards[0]))

        self.assertEqual(response.status_code, 405)
        self.assert_db_unchanged(cards_before, sources_before)

    def test_verify_sets_true_and_redirects_to_own_source(self):
        source, cards = self.make_source()

        response = self.client.post(
            self.review_url(cards[0]),
            {'action': 'verify'},
        )

        self.assertRedirects(response, self.detail_url(source))
        cards[0].refresh_from_db()
        self.assertTrue(cards[0].is_verified)

    def test_repeated_verify_keeps_true(self):
        source, cards = self.make_source()

        for _ in range(2):
            response = self.client.post(
                self.review_url(cards[0]),
                {'action': 'verify'},
            )
            self.assertEqual(response.status_code, 302)
            cards[0].refresh_from_db()
            self.assertTrue(cards[0].is_verified)

    def test_reset_sets_false(self):
        source, cards = self.make_source(verified=(1,))

        response = self.client.post(
            self.review_url(cards[0]),
            {'action': 'reset'},
        )

        self.assertRedirects(response, self.detail_url(source))
        cards[0].refresh_from_db()
        self.assertFalse(cards[0].is_verified)

    def test_reset_on_unverified_card_stays_false(self):
        source, cards = self.make_source()

        self.client.post(self.review_url(cards[0]), {'action': 'reset'})

        cards[0].refresh_from_db()
        self.assertFalse(cards[0].is_verified)

    def test_unknown_or_missing_action_returns_400_and_writes_nothing(self):
        source, cards = self.make_source(verified=(1,))
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        payloads = [
            {},
            {'action': ''},
            {'action': 'toggle'},
            {'action': 'VERIFY'},
            {'action': 'delete'},
        ]

        for payload in payloads:
            with self.subTest(payload=payload):
                for card in (cards[0], cards[1]):
                    response = self.client.post(
                        self.review_url(card),
                        payload,
                    )
                    self.assertEqual(response.status_code, 400)
                self.assert_db_unchanged(cards_before, sources_before)

    def test_review_changes_only_this_card(self):
        source, cards = self.make_source()
        other_source, other_cards = self.make_source(title='Басқа')

        self.client.post(self.review_url(cards[0]), {'action': 'verify'})

        verified = list(
            Flashcard.objects.filter(is_verified=True)
            .values_list('pk', flat=True)
        )
        self.assertEqual(verified, [cards[0].pk])

    def test_detail_counts_come_from_database_after_review(self):
        source, cards = self.make_source()

        self.client.post(self.review_url(cards[0]), {'action': 'verify'})
        response = self.client.get(self.detail_url(source))

        self.assertEqual(response.context['total_count'], 3)
        self.assertEqual(response.context['verified_count'], 1)
        self.assertEqual(response.context['pending_count'], 2)
        self.assertContains(response, 'Тексерілді 1 / 3')
        self.assertContains(response, 'Қалды 2')

        self.client.post(self.review_url(cards[0]), {'action': 'reset'})
        response = self.client.get(self.detail_url(source))

        self.assertEqual(response.context['verified_count'], 0)
        self.assertEqual(response.context['pending_count'], 3)
        self.assertContains(response, 'Тексерілді 0 / 3')

    def test_edit_after_verify_returns_card_to_pending(self):
        source, cards = self.make_source()

        self.client.post(self.review_url(cards[0]), {'action': 'verify'})
        self.client.post(
            self.edit_url(cards[0]),
            self.valid_edit_data(),
        )

        response = self.client.get(self.detail_url(source))
        self.assertEqual(response.context['verified_count'], 0)
        self.assertEqual(response.context['pending_count'], 3)


class SourceDetailFilterTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        # A: 1 және 3 тексерілген, 2 тексерілмеген
        self.source_a, self.cards_a = self.make_source(
            title='A',
            verified=(1, 3),
        )
        # B: бәрі тексерілген (A сүзгілеріне кірмеуі керек)
        self.source_b, self.cards_b = self.make_source(
            title='B',
            verified=(1, 2, 3),
        )

    def card_pks(self, response):
        return [card.pk for card in response.context['cards']]

    def test_default_shows_all_cards_of_own_source_in_order(self):
        response = self.client.get(self.detail_url(self.source_a))

        self.assertEqual(response.context['status'], 'all')
        self.assertEqual(
            self.card_pks(response),
            [card.pk for card in self.cards_a],
        )
        self.assertContains(response, '<article class="study-card">', count=3)
        self.assertContains(
            response,
            '<summary>Жауапты көрсету</summary>',
            count=3,
        )

    def test_pending_filter_shows_only_pending_of_own_source(self):
        response = self.client.get(
            self.detail_url(self.source_a),
            {'status': 'pending'},
        )

        self.assertEqual(response.context['status'], 'pending')
        self.assertEqual(self.card_pks(response), [self.cards_a[1].pk])
        self.assertContains(response, '<article class="study-card">', count=1)

    def test_verified_filter_shows_only_verified_of_own_source(self):
        response = self.client.get(
            self.detail_url(self.source_a),
            {'status': 'verified'},
        )

        self.assertEqual(response.context['status'], 'verified')
        self.assertEqual(
            self.card_pks(response),
            [self.cards_a[0].pk, self.cards_a[2].pk],
        )
        self.assertContains(response, '<article class="study-card">', count=2)

    def test_other_source_cards_never_appear(self):
        other_pks = {card.pk for card in self.cards_b}

        for status in ('', 'pending', 'verified', 'abc'):
            with self.subTest(status=status):
                response = self.client.get(
                    self.detail_url(self.source_a),
                    {'status': status},
                )
                self.assertFalse(other_pks & set(self.card_pks(response)))
                for card in self.cards_b:
                    self.assertNotContains(response, self.edit_url(card))

    def test_counts_are_for_whole_source_regardless_of_filter(self):
        for status in ('', 'pending', 'verified', 'abc'):
            with self.subTest(status=status):
                response = self.client.get(
                    self.detail_url(self.source_a),
                    {'status': status},
                )
                self.assertEqual(response.context['total_count'], 3)
                self.assertEqual(response.context['verified_count'], 2)
                self.assertEqual(response.context['pending_count'], 1)
                self.assertContains(response, 'Барлығы (3)')
                self.assertContains(response, 'Тексеру керек (1)')
                self.assertContains(response, 'Тексерілген (2)')
                self.assertContains(response, 'Тексерілді 2 / 3')
                self.assertContains(response, 'Қалды 1')

    def test_unknown_status_falls_back_to_all(self):
        for value in ('abc', 'PENDING', 'Verified', '', ' pending'):
            with self.subTest(value=value):
                response = self.client.get(
                    self.detail_url(self.source_a),
                    {'status': value},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['status'], 'all')
                self.assertEqual(len(self.card_pks(response)), 3)

    def test_filter_links_and_active_marker(self):
        url = self.detail_url(self.source_a)

        response = self.client.get(url, {'status': 'pending'})

        self.assertContains(response, f'{url}?status=pending')
        self.assertContains(response, f'{url}?status=verified')
        self.assertContains(response, 'class="filter-link active"', count=1)
        self.assertContains(response, 'aria-current="page"', count=1)

    def test_cards_are_ordered_by_position_then_pk(self):
        source = Source.objects.create(
            title='Рет',
            text=DEMO_TEXT,
            generation_mode='demo',
        )
        for position in (3, 1, 2):
            data = DEMO_CARDS[position - 1]
            Flashcard.objects.create(
                source=source,
                position=position,
                question=data['question'],
                answer=data['answer'],
                source_quote=data['source_quote'],
            )

        response = self.client.get(self.detail_url(source))

        self.assertEqual(
            [card.position for card in response.context['cards']],
            [1, 2, 3],
        )

    def test_empty_pending_filter_shows_message_and_show_all_link(self):
        response = self.client.get(
            self.detail_url(self.source_b),
            {'status': 'pending'},
        )

        self.assertEqual(self.card_pks(response), [])
        self.assertContains(
            response,
            'Тексеруді қажет ететін карточка жоқ.',
        )
        self.assertContains(response, 'Барлығын көрсету')
        self.assertContains(response, self.detail_url(self.source_b))
        self.assertEqual(response.context['total_count'], 3)

    def test_empty_verified_filter_shows_message_and_show_all_link(self):
        source, cards = self.make_source(title='C')

        response = self.client.get(
            self.detail_url(source),
            {'status': 'verified'},
        )

        self.assertEqual(self.card_pks(response), [])
        self.assertContains(response, 'Тексерілген карточка әлі жоқ.')
        self.assertContains(response, 'Барлығын көрсету')

    def test_empty_source_shows_message_and_saved_text(self):
        source = Source.objects.create(
            title='Бос',
            text=DEMO_TEXT,
            generation_mode='demo',
        )

        for status in ('', 'pending', 'verified'):
            with self.subTest(status=status):
                response = self.client.get(
                    self.detail_url(source),
                    {'status': status},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['total_count'], 0)
                self.assertContains(response, 'карточкалар қалмады')
                self.assertContains(
                    response,
                    'Компьютерная сеть — это соединённые устройства',
                )

    def test_gets_do_not_write_or_call_generator(self):
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        for status in ('', 'pending', 'verified', 'abc'):
            self.client.get(
                self.detail_url(self.source_a),
                {'status': status},
            )
            self.client.get(
                self.detail_url(self.source_b),
                {'status': status},
            )

        self.assert_db_unchanged(cards_before, sources_before)
        self.generate_mock.assert_not_called()

    def test_source_text_is_escaped_and_line_breaks_kept(self):
        source = Source.objects.create(
            title='Escape',
            text='<script>alert(1)</script>\nекінші жол',
            generation_mode='demo',
        )

        response = self.client.get(self.detail_url(source))

        self.assertContains(
            response,
            '&lt;script&gt;alert(1)&lt;/script&gt;',
        )
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '<br')


class CsrfTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.csrf_client = Client(enforce_csrf_checks=True)

    def get_token(self, url):
        self.csrf_client.get(url)
        return self.csrf_client.cookies['csrftoken'].value

    def test_edit_post_without_token_is_rejected(self):
        source, cards = self.make_source(verified=(1,))
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        response = self.csrf_client.post(
            self.edit_url(cards[0]),
            self.valid_edit_data(),
        )

        self.assertEqual(response.status_code, 403)
        self.assert_db_unchanged(cards_before, sources_before)

    def test_delete_post_without_token_is_rejected(self):
        source, cards = self.make_source()
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        response = self.csrf_client.post(self.delete_url(cards[0]))

        self.assertEqual(response.status_code, 403)
        self.assert_db_unchanged(cards_before, sources_before)

    def test_review_post_without_token_is_rejected(self):
        source, cards = self.make_source()
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        for action in ('verify', 'reset'):
            response = self.csrf_client.post(
                self.review_url(cards[0]),
                {'action': action},
            )
            self.assertEqual(response.status_code, 403)

        self.assert_db_unchanged(cards_before, sources_before)

    def test_edit_post_with_token_works(self):
        source, cards = self.make_source(verified=(1,))
        token = self.get_token(self.edit_url(cards[0]))
        data = self.valid_edit_data()
        data['csrfmiddlewaretoken'] = token

        response = self.csrf_client.post(self.edit_url(cards[0]), data)

        self.assertEqual(response.status_code, 302)
        cards[0].refresh_from_db()
        self.assertEqual(cards[0].question, data['question'])
        self.assertFalse(cards[0].is_verified)

    def test_delete_post_with_token_works(self):
        source, cards = self.make_source()
        token = self.get_token(self.delete_url(cards[0]))

        response = self.csrf_client.post(
            self.delete_url(cards[0]),
            {'csrfmiddlewaretoken': token},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Flashcard.objects.filter(pk=cards[0].pk).exists())

    def test_review_post_with_token_works(self):
        source, cards = self.make_source()
        token = self.get_token(self.detail_url(source))

        response = self.csrf_client.post(
            self.review_url(cards[0]),
            {'action': 'verify', 'csrfmiddlewaretoken': token},
        )

        self.assertEqual(response.status_code, 302)
        cards[0].refresh_from_db()
        self.assertTrue(cards[0].is_verified)

    def test_detail_forms_contain_csrf_token(self):
        source, cards = self.make_source()

        response = self.client.get(self.detail_url(source))

        self.assertContains(
            response,
            'name="csrfmiddlewaretoken"',
            count=3,
        )


class MissingObjectTests(EditorTestCase):
    def test_missing_pk_returns_404(self):
        source, cards = self.make_source()
        cards_before = self.cards_snapshot()
        sources_before = self.sources_snapshot()

        responses = {
            'detail GET': self.client.get(self.detail_url(MISSING_PK)),
            'edit GET': self.client.get(self.edit_url(MISSING_PK)),
            'edit POST': self.client.post(
                self.edit_url(MISSING_PK),
                self.valid_edit_data(),
            ),
            'delete GET': self.client.get(self.delete_url(MISSING_PK)),
            'delete POST': self.client.post(self.delete_url(MISSING_PK)),
            'review POST': self.client.post(
                self.review_url(MISSING_PK),
                {'action': 'verify'},
            ),
        }

        for name, response in responses.items():
            with self.subTest(name):
                self.assertEqual(response.status_code, 404)

        self.assert_db_unchanged(cards_before, sources_before)

    def test_review_get_on_missing_pk_is_405(self):
        response = self.client.get(self.review_url(MISSING_PK))

        self.assertEqual(response.status_code, 405)