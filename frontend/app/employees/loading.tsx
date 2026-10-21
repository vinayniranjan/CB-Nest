// Suspense boundary for /employees/* pages, which read useSearchParams();
// required for `next build` to prerender these routes.
export default function EmployeesLoading() {
  return <p className="p-6 text-sm text-muted-foreground">Loading…</p>;
}
