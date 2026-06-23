import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// This middleware ensures proper routing for static export
export function middleware(request: NextRequest) {
  // Let Next.js handle all routing normally
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match all paths except static files
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
