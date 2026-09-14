import { finishesFor, finishLabel } from '../../lib/cardFinish'
import type { CardFinish } from '../../lib/cardFinish'

const SHORT_CODE: Record<Exclude<CardFinish, 'regular'>, string> = {
  reverse: 'Rev',
  non_holo: 'NH',
  poke_ball: 'PB',
  master_ball: 'MB',
}

/** The finish buttons shown beside a catalog search hit - "Regular" is the row's own
 *  click target everywhere this is used, so it isn't repeated here. Which buttons
 *  appear depends on the hit's own set (`finishesFor` in lib/cardFinish.ts): every
 *  set gets Reverse Holo and Non-Holo, and a set with the Poke Ball / Master Ball
 *  chase pulls (151, Prismatic Evolutions, Black Bolt, White Flare) gets those two as
 *  well. Kept as its own component because the inventory page's inline search and the
 *  edit dialog's card-search step both need the exact same buttons, and a hit's row
 *  is a sibling `<button>` rather than a wrapper - buttons can't nest - so this has to
 *  be a separate element either way. */
export function CardFinishButtons({ setName, onPick }: {
  setName: string | null | undefined
  onPick: (finish: CardFinish) => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-1 pr-2">
      {finishesFor(setName).map((finish) => (
        <button
          key={finish}
          type="button"
          onClick={() => onPick(finish)}
          title={`Add as ${finishLabel(finish)}`}
          className="rounded px-1.5 py-1 text-[10px] font-medium text-slate-500 dark:text-neutral-400 hover:bg-slate-100 dark:hover:bg-neutral-700 hover:text-slate-800 dark:hover:text-neutral-100"
        >
          {SHORT_CODE[finish]}
        </button>
      ))}
    </div>
  )
}
