const search = document.querySelector('#note-search');
if (search) search.addEventListener('input', () => {
  const query = search.value.trim().toLocaleLowerCase();
  const cards = [...document.querySelectorAll('[data-search]')];
  let count = 0;
  cards.forEach(card => { card.hidden = !card.dataset.search.includes(query); if (card.closest('.reading-list')) card.parentElement.hidden = card.hidden; if (!card.hidden) count++; });
  document.querySelector('#no-results').hidden = !query || count > 0 || cards.length === 0;
});
