import { finishesFor, finishLabel } from '../../lib/cardFinish'
import type { CardFinish } from '../../lib/cardFinish'

const SHORT_CODE: Record<Exclude<CardFinish, 'regular'>, string> = {
  reverse: 'Rev',
  non_holo: 'NH',
  poke_ball: 'PB',
  master_ball: 'MB',
}

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
