#!/usr/bin/env python3
import asyncio
import json
import logging
import httpx
import subprocess
import os
import shlex
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(name="MokkitirpatServer")

# Constants
NOTEBOOK_FILE = "bird_notebook.json"
MAX_TOTAL_SIZE = 50 * 1024  # 50KB
MAX_SECTION_SIZE = 10 * 1024  # 10KB per section
MAX_APPEND_LINES = 10

def _load_notebook() -> Dict:
    """Load notebook, create if missing."""
    if not os.path.exists(NOTEBOOK_FILE):
        return {
            "finnish_names": {"content": "", "updated": "", "size": 0},
            "good_observations": {"content": "", "updated": "", "size": 0},
            "focus_species": {"content": "", "updated": "", "size": 0},
            "local_notes": {"content": "", "updated": "", "size": 0}
        }
    try:
        with open(NOTEBOOK_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return _load_notebook()  # Recursive call returns default

def _save_notebook(data: Dict) -> None:
    """Save notebook with size validation."""
    total_size = sum(s["size"] for s in data.values())
    if total_size > MAX_TOTAL_SIZE:
        raise ValueError(f"Total notebook size {total_size} exceeds limit {MAX_TOTAL_SIZE}")
    with open(NOTEBOOK_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@mcp.tool
def read_bird_notebook(section: Optional[str] = None) -> str:
    """
    Read the bird observation notebook containing Finnish names, observation tips,
    focus species, and local notes.
    
    Args:
        section: Specific section to read. Options: 'finnish_names', 'good_observations',
                'focus_species', 'local_notes'. If None, returns formatted full notebook.
    
    Returns:
        str: Notebook content formatted as readable text.
    
    Examples:
        # Read everything
        read_bird_notebook()
        
        # Read just Finnish names
        read_bird_notebook('finnish_names')
    """
    try:
        notebook = _load_notebook()
        
        if section:
            if section not in notebook:
                return f"Section '{section}' not found. Available: {', '.join(notebook.keys())}"
            
            s = notebook[section]
            if not s["content"]:
                return f"Section '{section}' is empty."
            
            return f"## {section.replace('_', ' ').title()}\n{s['content']}\n\n(Updated: {s['updated'] or 'never'})"
        
        # Format full notebook
        output = []
        for name, section_data in notebook.items():
            if section_data["content"]:
                output.append(f"## {name.replace('_', ' ').title()}")
                output.append(section_data["content"])
                output.append(f"(Updated: {section_data['updated'] or 'never'})\n")
        
        return "\n".join(output) if output else "Notebook is empty."
        
    except Exception as e:
        return f"Error reading notebook: {str(e)}"

@mcp.tool
def append_bird_note(section: str, content: str) -> str:
    """
    Append new content to a notebook section. Enforces size limits and line count.
    
    Args:
        section: Section name ('finnish_names', 'good_observations', 'focus_species', 'local_notes')
        content: Text to append (max 10 lines)
    
    Returns:
        str: Success message or error.
    
    Examples:
        append_bird_note('finnish_names', 'Kurki = Crane (Grus grus)')
        append_bird_note('local_notes', 'Saw rare winter visitor today')
    """
    try:
        # Validate input
        lines = content.strip().split('\n')
        if len(lines) > MAX_APPEND_LINES:
            return f"Error: Content has {len(lines)} lines, maximum is {MAX_APPEND_LINES}"
        
        notebook = _load_notebook()
        
        if section not in notebook:
            return f"Error: Unknown section '{section}'. Use: {', '.join(notebook.keys())}"
        
        # Check size
        new_content = content.strip()
        new_size = len(new_content.encode('utf-8'))
        current_size = notebook[section]["size"]
        
        if current_size + new_size + 1 > MAX_SECTION_SIZE:  # +1 for newline
            return f"Error: Would exceed section limit. Current: {current_size}, adding: {new_size}, limit: {MAX_SECTION_SIZE}"
        
        # Append
        if notebook[section]["content"]:
            notebook[section]["content"] += "\n" + new_content
        else:
            notebook[section]["content"] = new_content
            
        notebook[section]["size"] = len(notebook[section]["content"].encode('utf-8'))
        notebook[section]["updated"] = datetime.now().isoformat()
        
        _save_notebook(notebook)
        return f"Added {len(lines)} line(s) to '{section}' (now {notebook[section]['size']} bytes)"
        
    except Exception as e:
        return f"Error appending note: {str(e)}"

@mcp.tool
def update_bird_section(section: str, content: str) -> str:
    """
    Replace entire section content. Use carefully - this overwrites existing content.
    
    Args:
        section: Section to update
        content: New content (must fit within 10KB limit)
    
    Returns:
        str: Success message or error.
    """
    try:
        notebook = _load_notebook()
        
        if section not in notebook:
            return f"Error: Unknown section '{section}'"
        
        new_size = len(content.encode('utf-8'))
        if new_size > MAX_SECTION_SIZE:
            return f"Error: Content too large ({new_size} bytes), limit is {MAX_SECTION_SIZE}"
        
        old_size = notebook[section]["size"]
        notebook[section]["content"] = content.strip()
        notebook[section]["size"] = new_size
        notebook[section]["updated"] = datetime.now().isoformat()
        
        _save_notebook(notebook)
        return f"Updated '{section}' ({old_size} → {new_size} bytes)"
        
    except Exception as e:
        return f"Error updating section: {str(e)}"

@mcp.tool
def list_bird_sections() -> str:
    """
    Show notebook overview with section sizes and update times.
    
    Returns:
        str: Formatted statistics about each section.
    """
    try:
        notebook = _load_notebook()
        total_size = sum(s["size"] for s in notebook.values())
        
        output = [f"Bird Notebook Stats (Total: {total_size}/{MAX_TOTAL_SIZE} bytes)\n"]
        
        for name, data in notebook.items():
            percent = (data["size"] / MAX_SECTION_SIZE) * 100
            status = "empty" if data["size"] == 0 else f"{percent:.1f}% full"
            updated = data["updated"][:10] if data["updated"] else "never"
            output.append(f"- {name}: {data['size']} bytes ({status}, updated: {updated})")
        
        return "\n".join(output)
        
    except Exception as e:
        return f"Error getting stats: {str(e)}"

@mcp.tool  
def clear_bird_section(section: str) -> str:
    """
    Clear a section's content (for cleanup or rotation).
    
    Args:
        section: Section to clear
        
    Returns:
        str: Confirmation message.
    """
    try:
        notebook = _load_notebook()
        
        if section not in notebook:
            return f"Error: Unknown section '{section}'"
            
        old_size = notebook[section]["size"]
        notebook[section]["content"] = ""
        notebook[section]["size"] = 0
        notebook[section]["updated"] = ""
        
        _save_notebook(notebook)
        return f"Cleared '{section}' (freed {old_size} bytes)"
        
    except Exception as e:
        return f"Error clearing section: {str(e)}"


@mcp.tool
def query_bird_observations(
    hours: int = 120,
    confidence: float = 0.8,
    species: str = "",
    counts: bool = False,
    raw: bool = False,
    full_only: bool = False,
    nonfull_only: bool = False,
    nrows: int = 3,
    minlag: float = 2.0,
    max_output_lines: int = 150
) -> str:
    """
    Query BirdNET-Analyzer observations from CSV files in the res/ directory. This installation
    is in Parikkala, Finland, roughly 61.5°N and 29°E, although the user is often in the capital area.
    
    This tool analyzes bird observation data from audio recordings processed by BirdNET-Analyzer.
    Each CSV file represents approximately one hour of audio analysis. The tool can filter by
    species, confidence levels, and temporal spacing, and can return either individual 
    observations or species counts.
    
    Args:
        hours (int): Number of hours of recent data to analyze (default: 120).
                    Uses the most recent N CSV files from res/ directory.
        confidence (float): Minimum confidence threshold (0.0-1.0, default: 0.8).
                           Higher values = more confident detections only.
        species (str): Species filter using regex pattern (default: "").
                      Can match scientific or common names, e.g., 'pöllö|Strix' for owls.
                      Common names are in Finnish here; searching in English doesn't work.
        counts (bool): Return observation counts per species instead of individual obs (default: False).
        raw (bool): Return raw observations without deduplication/filtering (default: False).
        full_only (bool): Only show species with exactly 'nrows' observations (default: False).
        nonfull_only (bool): Only show species with fewer than 'nrows' observations (default: False).
        nrows (int): Maximum observations per species when not using raw mode (default: 3).
        minlag (float): Minimum seconds between observations to avoid duplicates (default: 2.0).
        max_output_lines (int): Maximum output lines to prevent overwhelming responses (default: 150).
    
    Returns:
        str: Formatted bird observation data or error message.
             Format depends on options - either individual observations with timestamps
             or species counts with confidence levels.
    
    Examples:
        # Recent owl observations
        query_bird_observations(species='pöllö|Strix', hours=48)
        
        # Species counts from last day  
        query_bird_observations(counts=True, hours=24)
        
        # A few observations with onfidence over 0.9. (Not terribly useful if there's a lot.)
        query_bird_observations(confidence=0.9, nrows=5)

    General tips:
    - Do not try to guess bird name correspondences from Finnish to English or scientific, they 
      are easily to get wrong. Search the web instead. 
    - Confidence is as reported by BirdNET and doesn't mean a probability. Sometimes BirdNET gives
      wrong ids, and false positives are always possible when there is a lot of observations. 
      For a _single_ observation, to be sure we'd require at least the confidence level of 0.99,
      and it is more trustworthy when there are natural clusters over time, like the bird really visited 
      there. 
    - It's good to search web for other recent Finnish recordings if something seems odd, or 
      search for distribution and habits of the species in general.
    """
    
    try:
        # Build the command safely
        cmd_parts = ['.venv/bin/python', 'species.py']
        
        # Get the file list using shell command (equivalent to $(ls res/* | tail -N))
        file_list_cmd = f"ls res/* | tail -{hours}"
        try:
            file_result = subprocess.run(file_list_cmd, shell=True, capture_output=True, text=True, timeout=10)
            if file_result.returncode != 0:
                return f"Error getting file list: {file_result.stderr}"
            
            input_files = file_result.stdout.strip().split('\n')
            if not input_files or input_files == ['']:
                return "No CSV files found in res/ directory"
                
        except subprocess.TimeoutExpired:
            return "Timeout while getting file list"
        except Exception as e:
            return f"Error getting file list: {str(e)}"
        
        # Add input files
        cmd_parts.extend(input_files)
        
        # Add parameters
        cmd_parts.extend(['-p', str(confidence)])
        
        if species:
            cmd_parts.extend(['--species', species])
            
        if counts:
            cmd_parts.append('--counts')
            
        if raw:
            cmd_parts.append('--raw')
            
        if full_only:
            cmd_parts.append('--full-only')
            
        if nonfull_only:
            cmd_parts.append('--nonfull-only')
            
        if nrows != 3:  # Only add if different from default
            cmd_parts.extend(['-n', str(nrows)])
            
        if minlag != 2.0:  # Only add if different from default
            cmd_parts.extend(['-l', str(minlag)])
        
        # Execute the command
        try:
            result = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return f"Error running species.py: {result.stderr}"
            
            output_lines = result.stdout.strip().split('\n')
            total_lines = len(output_lines)
            
            # Truncate if necessary
            if total_lines > max_output_lines:
                truncated_output = '\n'.join(output_lines[:max_output_lines])
                return f"{truncated_output}\n\n[Output truncated: showing {max_output_lines} of {total_lines} total lines]"
            else:
                return result.stdout.strip()
                
        except subprocess.TimeoutExpired:
            return "Timeout while running species analysis (>30s)"
        except Exception as e:
            return f"Error executing species.py: {str(e)}"
            
    except Exception as e:
        return f"Unexpected error in bird observation query: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8065)

