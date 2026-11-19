from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.http import require_POST

from .demo import DEMO_TEXT, DEMO_TITLE
from .forms import FlashcardForm, SourceForm
from .models import Source, Flashcard
from .services import GenerationError, generate_cards


def home(request):
    configured_mode = getattr(settings, 'TEACHME_MODE', 'demo')
    mode = (
        configured_mode.strip().upper()
        if isinstance(configured_mode, str)
        else 'UNKNOWN'
    )

    sources = Source.objects.order_by('-created_at', '-id')

    if request.method == 'POST':
        form = SourceForm(request.POST)

        if form.is_valid():
            try:
                cards = generate_cards(form.cleaned_data['text'])
            except GenerationError as exc:
                form.add_error(None, str(exc))
            else:
                generation_mode = configured_mode.strip().lower()

                try:
                    with transaction.atomic():
                        source = Source.objects.create(
                            title=form.cleaned_data['title'],
                            text=form.cleaned_data['text'],
                            generation_mode=generation_mode,
                        )

                        for position, card in enumerate(cards, 1):
                            Flashcard.objects.create(
                                source=source,
                                position=position,
                                question=card['question'],
                                answer=card['answer'],
                                source_quote=card['source_quote'],
                            )

                except DatabaseError:
                    form.add_error(
                        None,
                        'Деректерді сақтау кезінде қате пайда болды. Қайта көріңіз.',
                    )
                else:
                    return redirect('source_detail', pk=source.pk)

    else:
        form = SourceForm(initial={
            'title': DEMO_TITLE,
            'text': DEMO_TEXT,
        })

    return render(request, 'study/home.html', {
        'form': form,
        'mode': mode,
        'sources': sources,
    })


def source_detail(request, pk):
    source = get_object_or_404(Source, pk=pk)

    # Санауыштар бүкіл жинаққа қатысты, сүзгіге тәуелсіз.
    stats = source.cards.aggregate(
        total_count=Count('id'),
        verified_count=Count('id', filter=Q(is_verified=True)),
    )
    total_count = stats['total_count']
    verified_count = stats['verified_count']
    pending_count = total_count - verified_count

    # Белгісіз мән "all" болады.
    status = request.GET.get('status', 'all')
    if status not in ('pending', 'verified'):
        status = 'all'

    cards = source.cards.order_by('position', 'id')
    if status == 'pending':
        cards = cards.filter(is_verified=False)
    elif status == 'verified':
        cards = cards.filter(is_verified=True)

    return render(request, 'study/source_detail.html', {
        'source': source,
        'cards': cards,
        'status': status,
        'total_count': total_count,
        'verified_count': verified_count,
        'pending_count': pending_count,
    })


def card_edit(request, pk):
    card = get_object_or_404(
        Flashcard.objects.select_related('source'),
        pk=pk,
    )
    source = card.source

    if request.method == 'POST':
        form = FlashcardForm(request.POST, instance=card)

        if form.is_valid():
            edited_card = form.save(commit=False)
            # Кез келген дұрыс өңдеуден кейін қайта тексеру керек.
            # POST ішіндегі is_verified форма өрісінде жоқ, ескерілмейді.
            edited_card.is_verified = False

            try:
                edited_card.save(update_fields=[
                    'question',
                    'answer',
                    'source_quote',
                    'is_verified',
                ])
            except DatabaseError:
                form.add_error(
                    None,
                    'Деректерді сақтау кезінде қате пайда болды. Қайта көріңіз.',
                )
            else:
                return redirect('source_detail', pk=source.pk)
    else:
        form = FlashcardForm(instance=card)

    return render(request, 'study/card_form.html', {
        'form': form,
        'card': card,
        'source': source,
    })


def card_delete(request, pk):
    card = get_object_or_404(
        Flashcard.objects.select_related('source'),
        pk=pk,
    )
    source = card.source
    error = None

    if request.method == 'POST':
        source_id = card.source_id

        try:
            card.delete()
        except DatabaseError:
            error = 'Карточканы өшіру кезінде қате пайда болды. Қайта көріңіз.'
        else:
            return redirect('source_detail', pk=source_id)

    return render(request, 'study/card_confirm_delete.html', {
        'card': card,
        'source': source,
        'error': error,
    })


@require_POST
def card_review(request, pk):
    card = get_object_or_404(Flashcard, pk=pk)
    action = request.POST.get('action')

    if action == 'verify':
        new_value = True
    elif action == 'reset':
        new_value = False
    else:
        return HttpResponseBadRequest('Белгісіз әрекет.')

    try:
        Flashcard.objects.filter(pk=card.pk).update(is_verified=new_value)
    except DatabaseError:
        return HttpResponse(
            'Деректерді сақтау кезінде қате пайда болды. Қайта көріңіз.',
            status=500,
        )

    return redirect('source_detail', pk=card.source_id)