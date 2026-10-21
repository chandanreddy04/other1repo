#!/bin/bash

echo "🧪 Running Made It Home API Tests"
echo "================================="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source venv/bin/activate

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -q -r requirements.txt

# Run tests
echo -e "\n${YELLOW}Running tests...${NC}\n"
python -m pytest tests/ -v --tb=short

# Check test result
if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}✅ All tests passed!${NC}"
else
    echo -e "\n${RED}❌ Some tests failed${NC}"
    exit 1
fi

# Run coverage report
echo -e "\n${YELLOW}Running coverage report...${NC}"
python -m pytest tests/ --cov=app --cov-report=term-missing --cov-report=html

echo -e "\n${GREEN}Coverage report generated in htmlcov/index.html${NC}"
