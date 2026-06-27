const BASE = '/api';

async function fetchJson(url) {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) throw new Error(`API error: ${res.statusText}`);
  return res.json();
}

export function fetchCards() {
  return fetchJson('/cards');
}

export function fetchCardHistory(cardQuery) {
  return fetchJson(`/cards/${encodeURIComponent(cardQuery)}/history`);
}

export function fetchCardListings(cardQuery) {
  return fetchJson(`/cards/${encodeURIComponent(cardQuery)}/listings`);
}
