import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchCards } from '../api.js'

function currency(n) {
  return `$${Number(n).toFixed(2)}`
}

export default function Dashboard() {
  const { data: cards, isLoading, error } = useQuery({
    queryKey: ['cards'],
    queryFn: fetchCards,
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="loading">Loading prices...</div>
  if (error) return <div className="error">Failed to load: {error.message}</div>
  if (!cards?.length) return <div className="loading">No price data yet. Run <code>python main.py</code> first.</div>

  return (
    <div>
      <div className="header-row">
        <h2>Today's Prices</h2>
      </div>
      <div className="listings-table">
        <table>
          <thead>
            <tr>
              <th>Card</th>
              <th>Wtd Avg</th>
              <th>Median</th>
              <th>Avg</th>
              <th>Min</th>
              <th>Max</th>
              <th>n</th>
            </tr>
          </thead>
          <tbody>
            {cards.map((card) => (
              <tr key={card.card_query}>
                <td>
                  <Link to={`/cards/${encodeURIComponent(card.card_query)}`} className="card-link">
                    {card.card_query}
                  </Link>
                </td>
                <td className="price">{currency(card.weighted_avg)}</td>
                <td>{currency(card.median_price)}</td>
                <td>{currency(card.avg_price)}</td>
                <td>{currency(card.min_price)}</td>
                <td>{currency(card.max_price)}</td>
                <td>{card.sample_size}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
