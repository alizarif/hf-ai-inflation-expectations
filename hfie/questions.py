"""Survey questions, verbatim. Asked together in one message, in this order."""

QUESTIONS = {
    'Q1_I': 'Over the last 12 months, what do you think the overall rate of inflation/deflation has been in the economy? The rate of inflation/deflation was [Your answer as a number] percent over the last 12 months.\nIf you think there was inflation, please enter a positive number. If you think there was deflation, please enter a negative number. If you think there was neither inflation nor deflation, please enter zero.',

    'Q2_I': 'In THIS question, you will be asked about the probability (PERCENT CHANCE) of something happening. The\npercent chance must be a number between 0 and 100 and the sum of your answers must add up to 100.\nWhat do you think is the percent chance that, over the next 12 months...\n[RANGE OF EACH OPTION BELOW is 0-100 and each option can be 2 DECIMAL POINTS but the most important thing is that the total should be 100%]\n• the rate of deflation (opposite of inflation) will be 12% or more ______\n• the rate of deflation (opposite of inflation) will be between 8% and 12% ______\n• the rate of deflation (opposite of inflation) will be between 4% and 8% ______\n• the rate of deflation (opposite of inflation) will be between 2% and 4% ______\n• the rate of deflation (opposite of inflation) will be between 0% and 2% ______\n• the rate of inflation will be between 0% and 2% ______\n• the rate of inflation will be between 2% and 4% ______\n• the rate of inflation will be between 4% and 8% ______\n• the rate of inflation will be between 8% and 12% ______\n• the rate of inflation will be 12% or more______\nGive your answer as a list like this: [______%,______%,______%,______%,______%,______%,______%,______%,______%,______%]',

    'Q3_I': 'In THIS question, you will be asked about the probability (PERCENT CHANCE) of something happening. The\npercent chance must be a number between 0 and 100 and the sum of your answers must add up to 100.\nWhat do you think is the percent chance that over the 12-month period between 48 months from now and 60 months from now...\n[RANGE OF EACH OPTION BELOW is 0-100 and each option can be 2 DECIMAL POINTS but the most important thing is that the total should be 100%]\n• the rate of deflation (opposite of inflation) will be 12% or more ______\n• the rate of deflation (opposite of inflation) will be between 8% and 12% ______\n• the rate of deflation (opposite of inflation) will be between 4% and 8% ______\n• the rate of deflation (opposite of inflation) will be between 2% and 4% ______\n• the rate of deflation (opposite of inflation) will be between 0% and 2% ______\n• the rate of inflation will be between 0% and 2% ______\n• the rate of inflation will be between 2% and 4% ______\n• the rate of inflation will be between 4% and 8% ______\n• the rate of inflation will be between 8% and 12% ______\n• the rate of inflation will be 12% or more______\nGive your answer as a list like this: [______%,______%,______%,______%,______%,______%,______%,______%,______%,______%]',

    'Q4_I': 'What do you expect the rate of inflation to be over the next 12 months? Please give your best guess. Over the next 12 months, I expect the rate of inflation to be ___ %',

    'Q5_I': 'What do you expect the rate of inflation to be over that period? Please give your best guess. Over the 12-month period between 48 months from now and 60 months from now, I expect the rate of inflation to be ___ %',
}

POINT_QUESTIONS = ("Q1_I", "Q4_I", "Q5_I")
DENSITY_QUESTIONS = ("Q2_I", "Q3_I")

# Bin edges in the order asked (deflation >=12% ... inflation >=12%), as inflation rates.
# Open-ended outer bins are closed at +/-16 for the descriptive midpoint summary only.
BIN_EDGES = [(-16, -12), (-12, -8), (-8, -4), (-4, -2), (-2, 0),
             (0, 2), (2, 4), (4, 8), (8, 12), (12, 16)]
BIN_MIDPOINTS = [(lo + hi) / 2 for lo, hi in BIN_EDGES]
