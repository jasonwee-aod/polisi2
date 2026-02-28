import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";

type RouteDecision =
  | { action: "allow" }
  | { action: "redirect"; destination: string };

export function resolveRouteAccess(pathname: string, hasSession: boolean): RouteDecision {
  if (pathname.startsWith("/auth")) {
    return hasSession ? { action: "redirect", destination: "/chat" } : { action: "allow" };
  }

  if (pathname === "/") {
    return hasSession
      ? { action: "redirect", destination: "/chat" }
      : { action: "redirect", destination: "/auth?next=%2Fchat" };
  }

  if (pathname.startsWith("/chat") && !hasSession) {
    return { action: "redirect", destination: `/auth?next=${encodeURIComponent(pathname)}` };
  }

  return { action: "allow" };
}

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({
    request: {
      headers: request.headers
    }
  });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(entries) {
          entries.forEach(({ name, value, options }) => request.cookies.set(name, value));
          response = NextResponse.next({
            request: {
              headers: request.headers
            }
          });
          entries.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        }
      }
    }
  );

  const {
    data: { user }
  } = await supabase.auth.getUser();
  const decision = resolveRouteAccess(request.nextUrl.pathname, Boolean(user));

  if (decision.action === "redirect") {
    return NextResponse.redirect(new URL(decision.destination, request.url));
  }

  return response;
}

export const config = {
  matcher: ["/", "/auth", "/chat/:path*"]
};
