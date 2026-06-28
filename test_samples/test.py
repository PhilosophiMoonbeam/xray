# Python test file
import os
import sys
from typing import List, Dict, Optional
from dataclasses import dataclass
import asyncio

# Class definition
class DataProcessor:
    def __init__(self, config: Dict[str, any]):
        self.config = config
        self.data = []
    
    def process(self, items: List[str]) -> List[str]:
        """Process a list of items."""
        return [self._transform(item) for item in items]
    
    def _transform(self, item: str) -> str:
        """Transform a single item."""
        return item.upper()
    
    @staticmethod
    def validate(data: any) -> bool:
        """Validate data."""
        return bool(data)

# Dataclass
@dataclass
class User:
    id: int
    name: str
    email: str
    
    def get_display_name(self) -> str:
        return f"{self.name} <{self.email}>"

# Function definitions
def fetch_data(url: str) -> Dict[str, any]:
    """Fetch data from a URL."""
    # Implementation
    return {"data": []}

async def async_fetch(url: str) -> Dict[str, any]:
    """Async fetch data."""
    await asyncio.sleep(1)
    return fetch_data(url)

# Lambda function
transform = lambda x: x * 2

# Generator function
def data_generator(n: int):
    """Generate n items."""
    for i in range(n):
        yield i * 2

# Using imported modules
def main():
    processor = DataProcessor({"debug": True})
    user = User(1, "John", "john@example.com")
    
    # Function calls
    data = fetch_data("https://api.example.com")
    processed = processor.process(["a", "b", "c"])
    
    # Method calls
    display_name = user.get_display_name()
    is_valid = DataProcessor.validate(data)
    
    print(f"User: {display_name}")
    print(f"Valid: {is_valid}")

if __name__ == "__main__":
    main()
