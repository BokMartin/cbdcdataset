const navToggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('#site-nav');

navToggle?.addEventListener('click', () => {
  const isOpen = nav.classList.toggle('open');
  navToggle.setAttribute('aria-expanded', String(isOpen));
});

nav?.addEventListener('click', (event) => {
  if (event.target.matches('a')) {
    nav.classList.remove('open');
    navToggle?.setAttribute('aria-expanded', 'false');
  }
});

const displayNumber = (value, digits = 3) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
};

const centreLabel = (value) => String(value || 'no eligible evidence')
  .replaceAll('_', ' ')
  .replace(/\b\w/g, (character) => character.toUpperCase());

let entities = [];
let sortKey = 'country';
let ascending = true;

function renderEntities() {
  const body = document.querySelector('#entity-table tbody');
  if (!body) return;
  const query = document.querySelector('#entity-search')?.value.trim().toLowerCase() || '';
  const filtered = entities
    .filter((row) => `${row.country} ${row.jur} ${row.iso3}`.toLowerCase().includes(query))
    .sort((left, right) => {
      const a = left[sortKey];
      const b = right[sortKey];
      if (a === null || a === undefined) return 1;
      if (b === null || b === undefined) return -1;
      const direction = ascending ? 1 : -1;
      return (typeof a === 'number' ? a - b : String(a).localeCompare(String(b))) * direction;
    });
  body.innerHTML = filtered.map((row) => `
    <tr>
      <td><strong>${row.country}</strong><br><span class="small">${row.jur}</span></td>
      <td>${centreLabel(row.dominant_centre)}</td>
      <td>${displayNumber(row.privacy_family_share)}</td>
      <td>${displayNumber(row.privacy_posture)}</td>
      <td>${displayNumber(row.analytic_candidate_mass, 1)}</td>
    </tr>`).join('') || '<tr><td colspan="5">No matching entities.</td></tr>';
}

fetch('data/entities.json')
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    entities = data.entities;
    renderEntities();
  })
  .catch(() => {
    const body = document.querySelector('#entity-table tbody');
    if (body) body.innerHTML = '<tr><td colspan="5">The entity table could not be loaded. Download the CSV below.</td></tr>';
  });

document.querySelector('#entity-search')?.addEventListener('input', renderEntities);
document.querySelectorAll('#entity-table th[data-sort]').forEach((header) => {
  header.addEventListener('click', () => {
    const nextKey = header.dataset.sort;
    ascending = nextKey === sortKey ? !ascending : true;
    sortKey = nextKey;
    renderEntities();
  });
});

document.querySelector('.copy-button')?.addEventListener('click', async (event) => {
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Copy unavailable';
  }
});
