#!/usr/bin/env python3

# ---------------------------------------------------------------------------------
# PrusaSlicer post-processor script: Start heating a tool before it is time for use
# ---------------------------------------------------------------------------------

import sys
import re
import os
import io
import subprocess

# Path to g-code file from command-line
gcodeFile = sys.argv[len(sys.argv)-1]

# Read g-code into memory
with open(gcodeFile, "r") as f:
  inputLines = f.readlines()
  
# Example cool: M104 S220 T0 ; set temperature ;cooldown
# Example heat: M109 S250 T1 ; set temperature and wait for it to be reached
# Example progress: M73 P1 R33
# Goal: Add 'preheat' to the final temperature with M104 a bit before the M109, by checking for M73 progress commands


regex_m109 = re.compile('^M109 .*(?P<tool>T[\d]+).*') # Matches a heat-and-wait command
regex_m104 = re.compile('^M104 .*(?P<tool>T[\d]+).*') # Matches a cool-and-continue command
regex_m104temp = re.compile('.*S(?P<temp>[^ ;]+).*') # Matches the temperature part of an m104 command
regex_temp = re.compile('^(?P<cmd>M10[49]) .*(?P<temp>S[\d]+).*(?P<tool>T[\d]+).*') # Matches a heat-and-wait command
regex_m73 = re.compile('^M73 .*(?P<remain>R[\d]+).*') # Matches a progress update command

outputLines = []

# Pass 1

PreHeatShortCount = 2
PreHeatLongCount = 5

for lineNum in range(len(inputLines)):
  inputLine = inputLines[lineNum]
  outputLines.append(inputLine)
  if lineNum == 0:
    continue
  
  m109Match = regex_m109.match(inputLine)
  if bool(m109Match):
    foundRemaining = None
    foundDifferentRemainingCount = 0
    lineNumShortPreHeat = None
    lineNumLongPreHeat = None

    # Build pre-heat command (built even if not needed)
    preheat = inputLine.replace("M109", "M104")
    commentPos = preheat.find(';')
    if commentPos >= 0:
      preheat = preheat[0:commentPos]
    else:
      preheat = preheat.replace('\n', '')
    preheat += ' ; pre-heat '
    
    
    tool = m109Match.group('tool')
    
    # find line to place pre-heat command on
    for checkLineNum in range(len(outputLines)-2, 0, -1):
      checkLine = outputLines[checkLineNum]
      
      # If we find an earlier m109 for this tool, just stop looking
      earlierM109 = regex_m109.match(checkLine)
      if bool(earlierM109) and earlierM109.group('tool') == tool:
        break
      
      # Find the earlier m104 cooldown command, and then determine where to place pre-heat command
      m104Match = regex_m104.match(checkLine)
      if bool(m104Match) and m104Match.group('tool') == tool:
        if ';cooldown' in checkLine:
            if foundDifferentRemainingCount < PreHeatShortCount:
              outputLines[checkLineNum] = '; Removed cool-down: ' + checkLine
            elif foundDifferentRemainingCount < PreHeatLongCount: # Short unused extruder, short pre-heat
              outputLines.insert(lineNumShortPreHeat, preheat + 'short\n')
            else: # Long unused extruder, long pre-heat and deep-freeze cooldown
              outputLines.insert(lineNumLongPreHeat, preheat + 'long\n')
              matchTemp = regex_m104temp.match(checkLine)
              # If it's a cooldown to higher than 130, replace it with more cooling (otherwise, leave it alone)
              if bool(matchTemp) and float(matchTemp.group('temp')) > 130:
                outputLines[checkLineNum] = 'M104 S130 ' + tool + ' ; Converted cool-down to deep-freeze: ' + checkLine
        break
      
      # Check for a 'remaining' command to determine where pre-heat should happen
      m73Match = regex_m73.match(checkLine)
      if bool(m73Match):
        remaining = m73Match.group('remain')
        if foundRemaining is None: # first 'remaining' found
          foundRemaining = remaining
        elif foundRemaining != remaining:
          foundRemaining = remaining # the found 'remaining' time will be used to compare against the next found
          foundDifferentRemainingCount += 1
          if foundDifferentRemainingCount == PreHeatShortCount: # nozzle needs more than 2 minutes to heat up (at least when testing this)
            lineNumShortPreHeat = checkLineNum
          elif foundDifferentRemainingCount == PreHeatLongCount: # nozzle needs even more time to heat up from 'deep freeze'
            lineNumLongPreHeat = checkLineNum


# Pass 2 - Remove any unnecessary temp commands - especially M109 since it can cause a wait even if up to temp
currentToolTemp = {}
currentToolTempGuaranteed = {}

for lineNum in range(len(outputLines)):
  outputLine = outputLines[lineNum]
  
  matchTemp = regex_temp.match(outputLine)
  if bool(matchTemp):
    cmd = matchTemp.group('cmd')
    temp = matchTemp.group('temp')
    tool = matchTemp.group('tool')
    
    if tool in currentToolTemp and currentToolTemp[tool] == temp:
      if cmd == 'M104':
        outputLines[lineNum] = '; already requested/stabilized temp: ' + outputLine
      elif cmd == 'M109':
        if currentToolTempGuaranteed[tool]:
          outputLines[lineNum] = '; already stabilized temp: ' + outputLine
        else:
          currentToolTempGuaranteed[tool] = True
    else:
      currentToolTemp[tool] = temp
      currentToolTempGuaranteed[tool] = cmd == 'M109'

# Output modified g-code to file
with open(gcodeFile, "w") as f:
  f.writelines(outputLines)
  