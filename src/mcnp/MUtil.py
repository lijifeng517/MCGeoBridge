
import re

FLOAT_PAT = r'^([+-]?(?:\d+.?\d*|.\d+))((?:[eE][+-]?\d+)|(?:[+-]\d+))$' 
def str2float(data_str):
    try:
        return float(data_str)
    except ValueError:
        match = re.match(FLOAT_PAT, data_str.strip())
        if match:
            num_part = match.group(1)
            exp_part = match.group(2)
            if exp_part[0] in 'eE':
                std_str = num_part + exp_part
                return float(std_str)
            else:
                std_str = num_part + 'E' + exp_part
                return float(std_str)
        else:
            raise ValueError(f"Invalid float number format: {data_str}")
