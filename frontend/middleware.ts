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
  // Public assets (the brand logo, app icons, the web manifest and any static
  // image) are excluded too: the login page shows them to signed-out visitors,
  // and the image optimiser and the browser's install prompt fetch them
  // without a session cookie — a redirect there serves HTML where they expect
  // an image or JSON.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest|api/|brand/|icons/|.*\\.(?:png|jpe?g|svg|webp|ico)$).*)",
  ],
};
