/**
 * Plain 404 for /admin/* when the signed-in user is not a super_admin.
 * Deliberately neutral — gives no hint that an admin surface exists.
 */
export function AdminNotFound() {
  return (
    <div className="flex h-screen items-center justify-center bg-white">
      <div className="text-center">
        <div className="text-6xl font-bold text-slate-300">404</div>
        <div className="mt-2 text-sm text-slate-500">Seite nicht gefunden.</div>
      </div>
    </div>
  )
}
