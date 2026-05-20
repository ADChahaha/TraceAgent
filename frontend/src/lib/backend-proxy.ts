export interface ForwardBackendOptions {
  backendBaseUrl?: string;
  fetcher?: typeof fetch;
}

const BODYLESS_METHODS = new Set(["GET", "HEAD"]);
const STRIPPED_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "expect",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "upgrade"
]);
const FORWARDED_RESPONSE_HEADERS = ["content-type", "cache-control"];

export async function forwardBackendRequest(
  request: Request,
  pathSegments: string[],
  options: ForwardBackendOptions = {}
): Promise<Response> {
  const backendBaseUrl =
    options.backendBaseUrl ?? process.env.BACKEND_BASE_URL ?? "http://localhost:8000";
  const fetcher = options.fetcher ?? fetch;
  const targetUrl = buildBackendUrl(backendBaseUrl, pathSegments, request.url);
  const method = request.method.toUpperCase();
  const headers = buildRequestHeaders(request.headers);
  const body = BODYLESS_METHODS.has(method) ? undefined : await buildForwardBody(request);

  let backendResponse: Response;
  try {
    backendResponse = await fetcher(targetUrl, {
      method,
      headers,
      body,
      cache: "no-store"
    });
  } catch {
    return Response.json({ detail: "backend unavailable" }, { status: 502 });
  }

  if ((backendResponse.headers.get("content-type") ?? "").includes("text/event-stream")) {
    return new Response(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: buildResponseHeaders(backendResponse.headers)
    });
  }

  return new Response(await backendResponse.text(), {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: buildResponseHeaders(backendResponse.headers)
  });
}

function buildBackendUrl(baseUrl: string, pathSegments: string[], requestUrl: string): string {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  const url = new URL(pathSegments.map(encodeURIComponent).join("/"), normalizedBase);
  url.search = new URL(requestUrl).search;
  return url.toString();
}

function buildRequestHeaders(sourceHeaders: Headers): Headers {
  const headers = new Headers(sourceHeaders);
  for (const header of STRIPPED_REQUEST_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function buildForwardBody(request: Request): Promise<BodyInit> {
  const contentType = request.headers.get("content-type") ?? "";
  if (contentType.includes("multipart/form-data")) {
    return await request.arrayBuffer();
  }
  return request.text();
}

function buildResponseHeaders(sourceHeaders: Headers): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = sourceHeaders.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  return headers;
}
