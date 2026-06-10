#!/bin/bash
# OmniCouncil Frontend Completeness Verification
# Run after any UI design implementation to catch遗漏
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")/src"
FAIL=0

echo "=== OmniCouncil Frontend Completeness Check ==="
echo ""

# 1. Check for hardcoded fetch URLs (must use API_BASE)
echo "[1/4] Checking for hardcoded fetch URLs..."
HARDCODED=$(grep -rn "fetch('/\|fetch(\"/" "$SRC_DIR/pages/" "$SRC_DIR/components/" --include="*.tsx" --include="*.ts" 2>/dev/null || true)
if [ -n "$HARDCODED" ]; then
  echo "  ❌ FAIL: Hardcoded fetch URLs found:"
  echo "$HARDCODED" | sed 's/^/    /'
  FAIL=1
else
  echo "  ✅ OK"
fi

# 2. Check for stale provider references
echo "[2/4] Checking for stale provider references..."
STALE=$(grep -rn "id: 'claude'\|id: 'copilot'\|id: 'perplexity'\|id: 'kimi'" "$SRC_DIR/pages/" "$SRC_DIR/components/" --include="*.tsx" --include="*.ts" 2>/dev/null || true)
if [ -n "$STALE" ]; then
  echo "  ❌ FAIL: Stale provider references found:"
  echo "$STALE" | sed 's/^/    /'
  FAIL=1
else
  echo "  ✅ OK"
fi

# 3. Check that V2 components are imported in at least one page
echo "[3/4] Checking V2 component usage..."
V2_COMPONENTS="ProviderStatusCard MetricsSummary AlertRecoveryPanel ProviderDetailPanel SessionLifecycleBadge SelectorHealthBadge CapabilityBadges"
for comp in $V2_COMPONENTS; do
  USED=$(grep -rl "$comp" "$SRC_DIR/pages/" --include="*.tsx" 2>/dev/null || true)
  if [ -z "$USED" ]; then
    echo "  ⚠️  WARNING: $comp not imported in any page"
  else
    echo "  ✅ $comp → $(basename "$USED" | tr '\n' ', ')"
  fi
done

# 4. Check that all pages use API_BASE
echo "[4/4] Checking API_BASE usage in all pages..."
for page in "$SRC_DIR/pages/"*.tsx; do
  if [ -f "$page" ]; then
    HAS_API=$(grep -c "API_BASE\|import.meta.env.VITE_API_BASE_URL" "$page" 2>/dev/null || true)
    HAS_API=${HAS_API:-0}
    if [ "$HAS_API" -eq 0 ]; then
      echo "  ⚠️  WARNING: $(basename "$page") does not use API_BASE"
    fi
  fi
done

echo ""
if [ "$FAIL" -eq 1 ]; then
  echo "❌ Verification FAILED — fix issues above before committing"
  exit 1
else
  echo "✅ All checks passed"
  exit 0
fi
