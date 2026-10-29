on run argv
	set jsPath to item 1 of argv as text
	set js to read (POSIX file jsPath) as «class utf8»
	tell application "Google Chrome"
		repeat with w from 1 to (count of windows)
			repeat with t from 1 to (count of tabs of window w)
				set u to URL of tab t of window w
				if u contains "zhipin.com" then
					try
						return execute (tab t of window w) javascript js
					on error errMsg number errNum
						return "JS_ERROR:" & errNum & ":" & errMsg
					end try
				end if
			end repeat
		end repeat
	end tell
	return "NO_ZHIPIN_TAB"
end run
