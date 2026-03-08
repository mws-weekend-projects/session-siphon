import { NextRequest, NextResponse } from "next/server";
import { getConversationsByConversationIds } from "@/lib/typesense";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const ids: string[] = body.ids;

    if (!Array.isArray(ids) || ids.length === 0) {
      return NextResponse.json(
        { error: "ids array is required" },
        { status: 400 }
      );
    }

    const results = await getConversationsByConversationIds(ids);
    return NextResponse.json(results);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Failed to fetch conversations";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
