def judge(pred, ans):
    old_flag = ans in pred
    if "True" in pred:
        pred = pred.replace("True", "1")
    else:
        pred = pred.replace("False", "0")
    if "yes" in pred.lower():
        pred = pred.lower().replace("yes", "1")
    if "no" in pred.lower() and "1" not in pred:
        pred = pred.lower().replace("no", "0")
    if ans in ("False", "false"):
        ans = "0"
    if ans in ("True", "true"):
        ans = "1"
    if ans in ("No", "no"):
        ans = "0"
    if ans in ("Yes", "yes"):
        ans = "1"
    if ans in ("None", "none"):
        ans = "0"
    if ", " in ans:
        ans = ans.split(", ")
    if not isinstance(ans, list) and ans.endswith(".0"):
        ans = ans[:-2]
    if not isinstance(ans, list):
        ans = [ans]
    new_flag = all(a in pred for a in ans)
    return old_flag or new_flag
