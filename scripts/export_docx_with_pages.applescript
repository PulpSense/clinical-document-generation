on run argv
	if (count of argv) is not 2 then
		error "Usage: osascript scripts/export_docx_with_pages.applescript input.docx output.pdf"
	end if
	set inputPath to item 1 of argv
	set outputPath to item 2 of argv
	set inputFile to POSIX file inputPath
	set outputFile to POSIX file outputPath

	tell application "Pages"
		activate
		set theDoc to open inputFile
		if theDoc is missing value then
			delay 1
			set theDoc to front document
		end if
		export theDoc to outputFile as PDF
		close theDoc saving no
	end tell
end run
