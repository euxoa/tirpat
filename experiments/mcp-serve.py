# Only the tool function here so far, directly from Sonnet 4. 
# Requires fastMCP (v2) but that requires python 3.10 oldest.
# So we'll need to update things a bit first.


import subprocess
import os
import shlex

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
    Query BirdNET-Analyzer observations from CSV files in the res/ directory.
    
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
                      Can match scientific or common names, e.g., 'owl|Strix' for owls.
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
        query_bird_observations(species='owl|Strix', hours=48)
        
        # Species counts from last day  
        query_bird_observations(counts=True, hours=24)
        
        # High-confidence observations
        query_bird_observations(confidence=0.9, nrows=5)
    """
    
    try:
        # Build the command safely
        cmd_parts = ['python', 'species.py']
        
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


