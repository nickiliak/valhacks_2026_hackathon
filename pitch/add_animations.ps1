param([string]$Deck)
# Adds entrance animations and slide transitions with the installed PowerPoint.
# build_deck.py names every shape "<group>#<id>"; all shapes of a group appear together.
# The deck is complete without this step: every shape is visible in the PDF and in edit view.
$ErrorActionPreference = "Stop"
$FADE = 10; $ZOOM = 48; $WIPE = 22            # entrance effects: Fade, Faded Zoom, Wipe
$CLICK = 1; $WITH = 2; $AFTER = 3             # start on click / with previous / after previous

# slide, group, start, delay in seconds
$plan = @(
    @(1, "s1-tile1",   $AFTER, 0.4),          # the two amounts fade in by themselves
    @(1, "s1-tile2",   $WITH,  1.0),
    @(1, "s1-heading", $CLICK, 0.0),          # click 1: "We studied more than 78,000 bookings"
    @(1, "s1-card1",   $CLICK, 0.0),          # click 2: first question
    @(1, "s1-card2",   $CLICK, 0.0),          # click 3: second question
    @(1, "s1-card3",   $CLICK, 0.0),          # click 4: third question
    @(1, "s1-example", $CLICK, 0.0),          # click 5: the real request, boxes left to right
    @(1, "s1-chip1",   $WITH,  0.4),
    @(1, "s1-chip2",   $WITH,  0.8),
    @(1, "s1-chip3",   $WITH,  1.2),
    @(1, "s1-chip4",   $WITH,  1.6),
    @(2, "s2-chart",   $CLICK, 0.0),          # click 1: the bars grow from the left
    @(2, "s2-stat1",   $CLICK, 0.0),          # click 2: the three figures, one after another
    @(2, "s2-stat2",   $WITH,  0.5),
    @(2, "s2-stat3",   $WITH,  1.0)
)

$wasRunning = [bool](Get-Process POWERPNT -ErrorAction SilentlyContinue)
$ppt = New-Object -ComObject PowerPoint.Application
$pres = $ppt.Presentations.Open($Deck, 0, 0, 0)
try {
    foreach ($slide in $pres.Slides) {
        $sequence = $slide.TimeLine.MainSequence
        while ($sequence.Count -gt 0) { $sequence.Item(1).Delete() }
        $slide.SlideShowTransition.EntryEffect = 3849   # fade smoothly
        $slide.SlideShowTransition.Duration = 0.6
    }
    foreach ($step in $plan) {
        $slide = $pres.Slides.Item($step[0])
        $sequence = $slide.TimeLine.MainSequence
        $first = $true
        foreach ($shape in $slide.Shapes) {
            if ($shape.Name -notlike ($step[1] + "#*")) { continue }
            $kind = $FADE
            if ($shape.Name -like "*icon*") { $kind = $ZOOM }
            if ($shape.HasChart -eq -1) { $kind = $WIPE }
            $start = if ($first) { $step[2] } else { $WITH }
            $effect = $sequence.AddEffect($shape, $kind, 0, $start)
            $effect.Timing.Duration = if ($kind -eq $WIPE) { 1.0 } else { 0.5 }
            $effect.Timing.TriggerDelayTime = $step[3]
            if ($kind -eq $WIPE) { $effect.EffectParameters.Direction = 4 }   # from the left
            $first = $false
        }
        if ($first) { throw "No shapes found for animation group $($step[1])" }
    }
    $pres.Save()
    foreach ($slide in $pres.Slides) {
        $sequence = $slide.TimeLine.MainSequence
        $clicks = 0
        for ($i = 1; $i -le $sequence.Count; $i++) { if ($sequence.Item($i).Timing.TriggerType -eq $CLICK) { $clicks++ } }
        "slide $($slide.SlideIndex): $($sequence.Count) animated shapes, $clicks clicks"
    }
}
finally {
    $pres.Close()
    if (-not $wasRunning) { $ppt.Quit() }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
