#!/bin/bash
# build_refresh_lambda.sh
# DEPRECATED: This script is now merged into build_and_push.sh

echo "⚠️  DEPRECATED: This script has been merged into build_and_push.sh"
echo ""
echo "The build_and_push.sh script now handles all Lambda functions:"
echo "  • Scanner worker (ECS)"
echo "  • API Lambda"
echo "  • Refresh Lambda (if deployed)"
echo ""
echo "To build and deploy all components, run:"
echo "  ./build_and_push.sh"
echo ""
echo "Redirecting to build_and_push.sh in 3 seconds..."
sleep 3

exec ./build_and_push.sh
