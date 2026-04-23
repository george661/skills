/**
 * parseDraftContent.js
 * Parse draft content (JSON format) to extract nodes array.
 */

export default function parseDraftContent(content) {
  try {
    const parsed = JSON.parse(content);
    return parsed.nodes || [];
  } catch (e) {
    console.error('Failed to parse draft content:', e);
    return [];
  }
}
