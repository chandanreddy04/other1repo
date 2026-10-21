#!/bin/bash

echo "🚀 Made It Home - Setup Script"
echo "=============================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running on macOS or Linux
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    OS="linux"
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to print status
print_status() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $1${NC}"
    else
        echo -e "${RED}✗ $1${NC}"
        exit 1
    fi
}

# Check prerequisites
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

if command_exists docker; then
    echo -e "${GREEN}✓ Docker installed${NC}"
else
    echo -e "${RED}✗ Docker not found. Please install Docker first.${NC}"
    exit 1
fi

if command_exists python3; then
    echo -e "${GREEN}✓ Python 3 installed${NC}"
else
    echo -e "${RED}✗ Python 3 not found. Please install Python 3.11+${NC}"
    exit 1
fi

if command_exists node; then
    echo -e "${GREEN}✓ Node.js installed${NC}"
else
    echo -e "${RED}✗ Node.js not found. Please install Node.js 18+${NC}"
    exit 1
fi

# Create .env file if it doesn't exist
echo -e "\n${YELLOW}Setting up environment...${NC}"
if [ ! -f backend/.env ]; then
    cp backend/.env.example backend/.env
    echo -e "${GREEN}✓ Created .env file${NC}"
    echo -e "${YELLOW}  ⚠️  Please update backend/.env with your actual credentials${NC}"
else
    echo -e "${GREEN}✓ .env file already exists${NC}"
fi

# Start Docker services
echo -e "\n${YELLOW}Starting Docker services...${NC}"
docker-compose up -d postgres redis
print_status "PostgreSQL and Redis started"

# Wait for PostgreSQL to be ready
echo -e "\n${YELLOW}Waiting for PostgreSQL to be ready...${NC}"
sleep 5

# Setup Python virtual environment
echo -e "\n${YELLOW}Setting up Python environment...${NC}"
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_status "Virtual environment created"
fi

# Activate virtual environment
if [ "$OS" == "macos" ] || [ "$OS" == "linux" ]; then
    source venv/bin/activate
else
    source venv/Scripts/activate
fi

# Install Python dependencies
pip install -r requirements.txt
print_status "Python dependencies installed"

# Run database migrations
echo -e "\n${YELLOW}Running database migrations...${NC}"
alembic upgrade head
print_status "Database migrations completed"

# Go back to root
cd ..

# Setup mobile app
echo -e "\n${YELLOW}Setting up React Native app...${NC}"
cd mobile
npm install
print_status "React Native dependencies installed"

# iOS specific setup
if [ "$OS" == "macos" ]; then
    echo -e "\n${YELLOW}Setting up iOS dependencies...${NC}"
    cd ios
    if command_exists bundle; then
        bundle install
        bundle exec pod install
        print_status "iOS dependencies installed"
    else
        echo -e "${YELLOW}  ⚠️  Bundler not found. Run 'gem install bundler' then 'bundle install && bundle exec pod install' in mobile/ios${NC}"
    fi
    cd ..
fi

cd ..

# Create necessary directories
echo -e "\n${YELLOW}Creating directories...${NC}"
mkdir -p backend/uploads
mkdir -p mobile/src/assets/images

# Print next steps
echo -e "\n${GREEN}✅ Setup completed!${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo "1. Update backend/.env with your credentials:"
echo "   - AWS S3 credentials"
echo "   - Twilio credentials"
echo "   - Firebase credentials path"
echo "   - Secret key for production"
echo ""
echo "2. Start the backend:"
echo "   cd backend"
echo "   source venv/bin/activate"
echo "   uvicorn app.main:app --reload"
echo ""
echo "3. Start the mobile app:"
echo "   cd mobile"
echo "   npm start"
echo "   # In another terminal:"
echo "   npm run ios     # or npm run android"
echo ""
echo "4. For full setup with all services:"
echo "   docker-compose up"
echo ""
echo -e "${GREEN}Happy coding! 🎉${NC}"
