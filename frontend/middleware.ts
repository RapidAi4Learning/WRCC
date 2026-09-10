import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "wrcc_session";
const LOGIN_PATH = "/login";
const HOME_PATH = "/generate";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const authenticated = Boolean(request.cookies.get(SESSION_COOKIE)?.value);

  if (pathname === LOGIN_PATH) {
    if (authenticated) {
      return NextResponse.redirect(new URL(HOME_PATH, request.url));
    }
    return NextResponse.next();
  }

  if (!authenticated) {
    const login = new URL(LOGIN_PATH, request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  // Exclude API paths: the backend enforces their auth and returns JSON 401s.
  // Redirecting them to the HTML login page would break the same-origin proxy.
  // Public assets (the brand logo and any static image) are excluded too: the
  // login page shows the logo to signed-out visitors, and the image optimiser
  // fetches it without a session cookie — a redirect there serves HTML where
  // the optimiser expects an image.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/|brand/|.*\\.(?:png|jpe?g|svg|webp|ico)$).*)",
  ],
};
