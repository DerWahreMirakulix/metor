def clean_onion(onion):
    onion = onion.strip().lower()
    if onion.endswith(".onion"):
        onion = onion[:-6]
    return onion