#!/bin/bash

###############################################################################
# One-Time Setup - Enable Automatic Startup on SSH Login
# Run this once to configure startup.sh to run every time you SSH into the pod
###############################################################################

echo "🔧 Setting up automatic startup..."

# Make startup.sh executable
chmod +x /workspace/startup.sh
echo "✓ startup.sh is now executable"

# Add to .bashrc if not already present
if ! grep -q "/workspace/startup.sh" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# Auto-run AI Coding Agent startup script" >> ~/.bashrc
    echo "if [ -f /workspace/startup.sh ]; then" >> ~/.bashrc
    echo "    bash /workspace/startup.sh" >> ~/.bashrc
    echo "fi" >> ~/.bashrc
    echo "✓ Added startup.sh to .bashrc"
    echo ""
    echo "✅ Setup complete! The startup script will run automatically on every SSH login."
    echo ""
    echo "💡 To test now, run: bash /workspace/startup.sh"
else
    echo "✓ startup.sh already configured in .bashrc"
    echo ""
    echo "✅ Setup already complete!"
fi
