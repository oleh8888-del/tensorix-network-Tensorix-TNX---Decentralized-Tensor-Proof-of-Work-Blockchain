"""
Tensorix Network (TNX) - Difficulty Adjustment Algorithm (LWMA)
Linear Weighted Moving Average for smooth, responsive difficulty retargeting,
protecting against hash spikes and multipool hopping.
"""

TARGET_BLOCK_TIME = 60  # Target: 60 seconds per block
LWMA_WINDOW = 30        # Moving window of past 30 blocks
MIN_DIFFICULTY = 1.0


def calculate_next_difficulty(block_history: list) -> float:
    """
    Calculate next difficulty using LWMA algorithm.
    block_history is a list of recent blocks (dicts with 'timestamp' and 'difficulty'),
    ordered chronologically (oldest to newest).
    """
    if len(block_history) < 2:
        return MIN_DIFFICULTY
    
    window = min(len(block_history), LWMA_WINDOW)
    recent_blocks = block_history[-window:]
    
    # Calculate weighted solve times
    weighted_solve_time = 0.0
    weight_sum = 0.0
    
    for i in range(1, len(recent_blocks)):
        weight = float(i)
        # Solve time between block i and block i-1
        solve_time = recent_blocks[i]['timestamp'] - recent_blocks[i - 1]['timestamp']
        # Clamp individual solve time to avoid negative or crazy timestamps
        solve_time = max(1.0, min(float(solve_time), TARGET_BLOCK_TIME * 6.0))
        
        weighted_solve_time += solve_time * weight
        weight_sum += weight
    
    if weight_sum == 0:
        return recent_blocks[-1].get('difficulty', MIN_DIFFICULTY)
    
    avg_solve_time = weighted_solve_time / weight_sum
    current_difficulty = float(recent_blocks[-1].get('difficulty', MIN_DIFFICULTY))
    
    # Adjust difficulty proportionally: next_diff = current_diff * (target_time / actual_time)
    adjustment = TARGET_BLOCK_TIME / avg_solve_time
    
    # Dampen adjustment to max +/- 15% per block to ensure smooth curve
    adjustment = max(0.85, min(adjustment, 1.15))
    
    next_diff = current_difficulty * adjustment
    return max(MIN_DIFFICULTY, round(next_diff, 4))

