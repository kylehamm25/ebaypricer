/** Which physical print of a catalogued card a row actually is.
 *
 *  A single catalog entry (name + number + set) can exist as more than one finish -
 *  most commons/uncommons from 2002 onward come as a plain "Normal" pull or a
 *  "Reverse Holofoil" parallel, and holo-rarity cards have their holo finish as the
 *  only print at all. 'regular' and 'non_holo' are two labels for that same default,
 *  non-reverse state - which one reads naturally depends on the card's own rarity -
 *  so they are offered as separate buttons but treated identically here.
 *
 *  'poke_ball' and 'master_ball' are a further two reverse-holo-family prints found
 *  only in sets with the Poke Ball / Master Ball pattern chase pulls (151, Prismatic
 *  Evolutions, Black Bolt, White Flare - see BALL_PATTERN_SETS) - each trades apart
 *  from plain reverse holo and from the other ball pattern of the same card.
 *
 *  'reverse', 'poke_ball' and 'master_ball' each have a real functional effect:
 *  appending a suffix to card_query is the existing convention `cards.format_card()`
 *  already uses for "Reverse" when a listing title says so, and
 *  `comp_filter.evaluate_comp` screens the comp pool on exactly that suffix (plus,
 *  for the two ball patterns, `cards.card_identity`'s `pattern` field) - so picking
 *  any of the three here plugs into pricing logic that already exists, or a small,
 *  symmetric extension of it, rather than a display-only label. */
export type CardFinish = 'regular' | 'reverse' | 'non_holo' | 'poke_ball' | 'master_ball'

const FINISH_LABEL: Record<CardFinish, string> = {
  regular: 'Regular',
  reverse: 'Reverse Holo',
  non_holo: 'Non-Holo',
  poke_ball: 'Poke Ball Pattern',
  master_ball: 'Master Ball Pattern',
}

// The card_query suffix for each finish that has one - two tokens for the ball
// patterns, matching _BALL_PATTERN_TOKENS in cards.py exactly (that parser tries the
// two-token form first, so the order/spelling here has to stay in lockstep with it).
const FINISH_SUFFIX: Partial<Record<CardFinish, string>> = {
  reverse: ' Reverse',
  poke_ball: ' Poke Ball',
  master_ball: ' Master Ball',
}

export const FINISHES: CardFinish[] = ['regular', 'reverse', 'non_holo', 'poke_ball', 'master_ball']

// Sets known to carry the Poke Ball / Master Ball chase pulls. Lowercased for a
// case-insensitive match against the catalog's set_name field. Add a set here the day
// its ball patterns are confirmed to exist - offering the buttons on a set that has no
// such print would just tag rows with a phrase no comp will ever match.
const BALL_PATTERN_SETS = new Set(['prismatic evolutions', 'black bolt', 'white flare'])

export function hasBallPatterns(setName: string | null | undefined): boolean {
  return BALL_PATTERN_SETS.has((setName ?? '').trim().toLowerCase())
}

/** Which finishes to offer for a catalog hit - the two universal ones plus, only for
 *  a set known to carry them, the two ball patterns. 'regular' is never in this list:
 *  it is always the search result row's own click target, never a secondary button. */
export function finishesFor(setName: string | null | undefined): Exclude<CardFinish, 'regular'>[] {
  return hasBallPatterns(setName) ? ['reverse', 'non_holo', 'poke_ball', 'master_ball'] : ['reverse', 'non_holo']
}

export function finishLabel(finish: CardFinish): string {
  return FINISH_LABEL[finish]
}

/** Apply a chosen finish to a catalog hit's card_query and display name.
 *
 *  Only reverse-family finishes (reverse, poke_ball, master_ball) change card_query -
 *  the actual pricing/search key - because eBay sellers reliably call these out in the
 *  title, the same reasoning "Reverse" already relies on elsewhere in this app. "Non
 *  Holo" is not a phrase sellers reliably use for the default, unmarked print of a
 *  common, so forcing it into the search would drop good comps rather than filter out
 *  bad ones - the name suffix is where that distinction shows up instead. */
export function applyFinish(
  card: { card_query: string; name: string },
  finish: CardFinish,
): { card_query: string; name: string } {
  const suffix = FINISH_SUFFIX[finish]
  const card_query = suffix ? `${card.card_query}${suffix}` : card.card_query
  const nameSuffix = finish === 'regular' ? '' : ` (${finishLabel(finish)})`
  return { card_query, name: `${card.name}${nameSuffix}` }
}
