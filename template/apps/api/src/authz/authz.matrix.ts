// AUTHZ-1: who may call each route, keyed `METHOD /path` exactly as the router registers it
// (Express syntax, e.g. `GET /items/:id`). authz.matrix.spec.ts fails when a registered route is
// missing here or an entry matches no route, so no endpoint ships without an access decision.
//
// The auth guard, when it exists, reads this same table: a global guard (APP_GUARD) builds the key
// from `${req.method} ${req.route.path}`, lets 'public' through, otherwise requires the caller's
// role to be in the list, and denies a key it can't find (fail closed).

/** The roles a caller can hold. None until the product has accounts; then e.g. 'admin' | 'member'. */
export type Role = never;

export const authzMatrix = {
  'GET /health': 'public',
} as const satisfies Record<string, 'public' | readonly Role[]>;

export type Route = keyof typeof authzMatrix;
