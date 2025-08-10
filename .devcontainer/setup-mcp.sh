
# MCP
mkdir -p /root/Cline/MCP

# sequentialthinking
echo "sequentialthinking START"
mkdir -p /root/Cline/MCP/sequentialthinking
echo "sequentialthinking END"

# playwright-mcp-server
echo "playwright-mcp-server START"
npm install -g @executeautomation/playwright-mcp-server
apt-get update && apt-get install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libatspi2.0-0 libxcomposite1 libxdamage1
echo "playwright-mcp-server END"

# context7-mcp
echo "context7-mcp START"
mkdir -p /root/Cline/MCP/context7-mcp
echo "context7-mcp END"

echo "Cline MCP Setting Start!!"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p /root/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev/settings/
cp "$SCRIPT_DIR/cline_mcp_settings.json" "/root/.vscode-server/data/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"
echo "Cline MCP Setting END!!"
