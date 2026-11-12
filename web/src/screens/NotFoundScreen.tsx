import { Link } from 'react-router'

export function NotFoundScreen() {
  return (
    <div className="page">
      <div className="notfound">
        <h1>This page does not exist</h1>
        <p>The address may be mistyped, or the page was moved. Your documents and conversations are unaffected.</p>
        <Link to="/" className="btn btn-primary">
          Back to the workspace
        </Link>
      </div>
    </div>
  )
}
