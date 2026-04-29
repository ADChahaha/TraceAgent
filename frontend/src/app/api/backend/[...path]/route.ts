import { forwardBackendRequest } from "@/lib/backend-proxy";

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function handle(request: Request, context: RouteContext) {
  const { path } = await context.params;
  return forwardBackendRequest(request, path);
}

export async function GET(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function POST(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function PUT(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function PATCH(request: Request, context: RouteContext) {
  return handle(request, context);
}

export async function DELETE(request: Request, context: RouteContext) {
  return handle(request, context);
}
