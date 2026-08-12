# 測試正則表達式匹配
import re

test_code = 'object value = obj.GetFirstValue("Select M.Url From dbo.Roles as R inner join dbo.ModuleList as M on R.DefaultPageID = M.ItemID Where M.Status = \'Y\' and Role = @Role", par);'

patterns = [
    # 模式 1: variable.Method("SQL")
    r'(\w+)\s*\.\s*GetFirstValue\s*\(\s*"([^"]*?(?:SELECT|INSERT|UPDATE|DELETE)[^"]*?)"',
    # 模式 2: variable.Method(@"SQL")
    r'(\w+)\s*\.\s*GetFirstValue\s*\(\s*@"([^"]*?(?:SELECT|INSERT|UPDATE|DELETE)[^"]*?)"',
]

print("=" * 80)
print("測試正則表達式")
print("=" * 80)
print(f"\n測試字串: {test_code[:100]}...")

for i, pattern in enumerate(patterns, 1):
    print(f"\n模式 {i}: {pattern[:60]}...")
    matches = list(re.finditer(pattern, test_code, re.IGNORECASE | re.DOTALL))
    print(f"找到 {len(matches)} 個匹配")
    
    for match in matches:
        print(f"  變數名稱: {match.group(1)}")
        print(f"  SQL: {match.group(2)[:50]}...")
