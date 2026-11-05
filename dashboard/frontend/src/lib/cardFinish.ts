export type CardFinish = 'regular' | 'reverse' | 'non_holo' | 'poke_ball' | 'master_ball'

const FINISH_LABEL: Record<CardFinish, string> = {
  regular: 'Regular',
  reverse: 'Reverse Holo',
  non_holo: 'Non-Holo',
  poke_ball: 'Poke Ball Pattern',
  master_ball: 'Master Ball Pattern',
}

// The card_query suffix for each finish that has one - two tokens for the ball
// patterns and for Non Holo, matching what cards.card_identity() strips back out
// (it tries the two-token forms first, so the order/spelling here has to stay in
// lockstep with it). Every non-regular finish changes card_query, so each print
// gets its own eBay search and comp pool rather than sharing the regular one.
const FINISH_SUFFIX: Partial<Record<CardFinish, string>> = {
  reverse: ' Reverse',
  non_holo: ' Non Holo',
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

export function finishesFor(setName: string | null | undefined): Exclude<CardFinish, 'regular'>[] {
  return hasBallPatterns(setName) ? ['reverse', 'non_holo', 'poke_ball', 'master_ball'] : ['reverse', 'non_holo']
}

export function finishLabel(finish: CardFinish): string {
  return FINISH_LABEL[finish]
}

export function applyFinish(
  card: { card_query: string; name: string },
  finish: CardFinish,
): { card_query: string; name: string } {
  const suffix = FINISH_SUFFIX[finish]
  const card_query = suffix ? `${card.card_query}${suffix}` : card.card_query
  const nameSuffix = finish === 'regular' ? '' : ` (${finishLabel(finish)})`
  return { card_query, name: `${card.name}${nameSuffix}` }
}
