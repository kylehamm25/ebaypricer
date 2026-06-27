import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { fetchCardHistory, fetchCardListings } from '../api.js'

function currency(n) {
  return `$${Number(n).toFixed(2)}`
}

export default function CardDetail() {
  const { cardQuery } = useParams()

  const { data: history, isLoading: histLoading, error: histErr } = useQuery({
    queryKey: ['cardHistory', cardQuery],
    queryFn: () => fetchCardHistory(cardQuery),
  })

  const { data: listings, isLoading: listLoading } = useQuery({
    queryKey: ['cardListings', cardQuery],
    queryFn: () => fetchCardListings(cardQuery),
  })

  if (histLoading) return <div className="loading">Loading...</div>
  if (histErr) return <div className="error">Card not found</div>

  const latest = history?.[history.length - 1]

  return (
    <div>
      <Link to="/" className="back-link">&larr; Back to dashboard</Link>
      <h2 style={{ margin: '0 0 24px', color: 'var(--text-h)' }}>
        {latest?.card_query || cardQuery}
      </h2>

      {latest && (
        <div className="stat-grid">
          <div className="stat-card">
            <div className="label">Weighted Avg</div>
            <div className="value">{currency(latest.weighted_avg)}</div>
          </div>
          <div className="stat-card">
            <div className="label">Median</div>
            <div className="value">{currency(latest.median_price)}</div>
          </div>
          <div className="stat-card">
            <div className="label">Average</div>
            <div className="value">{currency(latest.avg_price)}</div>
          </div>
          <div className="stat-card">
            <div className="label">Min</div>
            <div className="value">{currency(latest.min_price)}</div>
          </div>
          <div className="stat-card">
            <div className="label">Max</div>
            <div className="value">{currency(latest.max_price)}</div>
          </div>
          <div className="stat-card">
            <div className="label">Sample Size</div>
            <div className="value">{latest.sample_size}</div>
          </div>
        </div>
      )}

      {history?.length > 1 && (
        <div className="chart-container">
          <h3>Price History</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="snapshot_date" tick={{ fontSize: 12 }} stroke="var(--muted)" />
              <YAxis tick={{ fontSize: 12 }} stroke="var(--muted)" tickFormatter={(v) => `$${v}`} />
              <Tooltip formatter={(v) => [`$${Number(v).toFixed(2)}`]} />
              <Line type="monotone" dataKey="weighted_avg" stroke="var(--accent)" strokeWidth={2} dot={false} name="Wtd Avg" />
              <Line type="monotone" dataKey="median_price" stroke="var(--muted)" strokeWidth={1.5} dot={false} name="Median" strokeDasharray="4 4" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="header-row">
        <h2>Recent Sold Listings</h2>
      </div>
      {listLoading ? (
        <div className="loading">Loading listings...</div>
      ) : (
        <div className="listings-table">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Price</th>
                <th>Condition</th>
                <th>Sold Date</th>
              </tr>
            </thead>
            <tbody>
              {listings?.map((item) => (
                <tr key={item.item_id}>
                  <td>
                    <a href={item.url} target="_blank" rel="noopener noreferrer">
                      {item.title}
                    </a>
                  </td>
                  <td className="price">{currency(item.price)}</td>
                  <td>{item.condition || '—'}</td>
                  <td>{item.sold_date?.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
