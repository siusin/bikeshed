# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals
import collections
import itertools
import re
from . import config
from . import lexers
from .htmlhelpers import *
from .messages import *
from .widlparser.widlparser import parser
try:
    import pygments as pyg
    from pygments.lexers import get_lexer_by_name
    from pygments import formatters
except ImportError:
    die("Bikeshed now uses Pygments for syntax highlighting.\nPlease run `$ sudo pip install pygments` from your command line.")

customLexers = {
    "css": lexers.CSSLexer()
}

ColoredText = collections.namedtuple('ColoredText', ['text', 'color'])

def addSyntaxHighlighting(doc):
    normalizeHighlightMarkers(doc)

    # Highlight all the appropriate elements
    highlightingOccurred = False
    lineWrappingOccurred = False
    lineHighlightingOccurred = False
    for el in findAll("xmp, pre, code", doc):
        # Find whether to highlight, and what the lang is
        lang = determineHighlightLang(doc, el)
        if lang is False:
            # Element was already highlighted, but needs styles
            highlightingOccurred = True
        elif lang:
            highlightEl(el, lang)
            highlightingOccurred = True
        # Find whether to add line numbers
        addLineNumbers, lineStart, lineHighlights = determineLineNumbers(doc, el)
        if addLineNumbers or lineHighlights:
            addLineWrappers(el, numbers=addLineNumbers, start=lineStart, highlights=lineHighlights)
            if addLineNumbers:
                lineWrappingOccurred = True
            if lineHighlights:
                lineHighlightingOccurred = True

    if highlightingOccurred:
        doc.extraStyles['style-syntax-highlighting'] += getHighlightStyles()
    if lineWrappingOccurred:
        doc.extraStyles['style-line-numbers'] += getLineNumberStyles()
    if lineHighlightingOccurred:
        doc.extraStyles['style-line-highlighting'] += getLineHighlightingStyles()


def determineHighlightLang(doc, el):
    # Either returns a normalized highlight lang,
    # False indicating the element was already highlighted,
    # or None indicating the element shouldn't be highlighted.
    attr, lang = closestAttr(el, "nohighlight", "highlight")
    lang = normalizeLanguageName(lang)
    if attr == "nohighlight":
        return None
    elif attr == "highlight":
        return lang
    else:
        # Highlight-by-default, if applicable.
        if el.tag in ["pre", "xmp"] and hasClass(el, "idl"):
            if isNormative(el):
                # Normative IDL gets 'highlighted' by the IDL parser.
                return False
            else:
                return "idl"
        else:
            return doc.md.defaultHighlight


def determineLineNumbers(doc, el):
    lAttr, _ = closestAttr(el, "no-line-numbers", "line-numbers")
    if lAttr == "no-line-numbers" or el.tag == "code":
        addLineNumbers = False
    elif lAttr == "line-numbers":
        addLineNumbers = True
    else:
        addLineNumbers = doc.md.lineNumbers

    lineStart = el.get("line-start")
    if lineStart is None:
        lineStart = 1
    else:
        try:
            lineStart = int(lineStart)
        except ValueError:
            die("line-start attribute must have an integer value. Got '{0}'.", lineStart, el=el)
            lineStart = 1

    lh = el.get("line-highlight")
    lineHighlights = set()
    if lh is None:
        pass
    else:
        lh = re.sub(r"\s*", "", lh)
        for item in lh.split(","):
            if "-" in item:
                # Range, format of DDD-DDD
                low,_,high = item.partition("-")
                try:
                    low = int(low)
                    high = int(high)
                except ValueError:
                    die("Error parsing line-highlight range '{0}' - must be `int-int`.", item, el=el)
                    continue
                if low >= high:
                    die("line-highlight ranges must be well-formed lo-hi - got '{0}'.", item, el=el)
                    continue
                lineHighlights.update(range(low, high+1))
            else:
                try:
                    item = int(item)
                except ValueError:
                    die("Error parsing line-highlight value '{0}' - must be integers.", item, el=el)
                    continue
                lineHighlights.add(item)

    return addLineNumbers, lineStart, lineHighlights


def highlightEl(el, lang):
    text = textContent(el)
    if lang in ["idl", "webidl"]:
        coloredText = highlightWithWebIDL(text, el=el)
    else:
        coloredText = highlightWithPygments(text, lang, el=el)
    mergeHighlighting(el, coloredText)
    addClass(el, "highlight")


def highlightWithWebIDL(text, el):
    class IDLUI(object):
        def warn(self, msg):
            die("{0}", msg.rstrip())
    class HighlightMarker(object):
        # Just applies highlighting classes to IDL stuff.
        def markupTypeName(self, text, construct):
            return ('<span class=n>', '</span>')
        def markupName(self, text, construct):
            return ('<span class=nv>', '</span>')
        def markupKeyword(self, text, construct):
            return ('<span class=kt>', '</span>')
        def markupEnumValue(self, text, construct):
            return ('<span class=s>', '</span>')

    widl = parser.Parser(text, IDLUI())
    nested = parseHTML(unicode(widl.markup(HighlightMarker())))
    coloredText = collections.deque()
    for n in childNodes(flattenHighlighting(nested)):
        if isElement(n):
            coloredText.append(ColoredText(textContent(n), n.get('class')))
        else:
            coloredText.append(ColoredText(n, None))
    return coloredText


def highlightWithPygments(text, lang, el):
    lexer = lexerFromLang(lang)
    if lexer is None:
        die("'{0}' isn't a known syntax-highlighting language. See http://pygments.org/docs/lexers/. Seen on:\n{1}", lang, outerHTML(el), el=el)
        return
    rawTokens = pyg.highlight(text, lexer, formatters.RawTokenFormatter())
    coloredText = coloredTextFromRawTokens(rawTokens)
    return coloredText


def mergeHighlighting(el, coloredText):
    # Merges a tree of Pygment-highlighted HTML
    # into the original element's markup.
    # This works because Pygment effectively colors each character with a highlight class,
    # merging them together into runs of text for convenience/efficiency only;
    # the markup structure is a flat list of sibling elements containing raw text
    # (and maybe some un-highlighted raw text between them).
    def createEl(color, text):
        return E.span({"class":color}, text)

    def colorizeEl(el, coloredText):
        for node in childNodes(el, clear=True):
            if isElement(node):
                appendChild(el, colorizeEl(node, coloredText))
            else:
                appendChild(el, *colorizeText(node, coloredText))
        return el

    def colorizeText(text, coloredText):
        nodes = []
        while text and coloredText:
            nextColor = coloredText.popleft()
            if len(nextColor.text) <= len(text):
                if nextColor.color is None:
                    nodes.append(nextColor.text)
                else:
                    nodes.append(createEl(nextColor.color, nextColor.text))
                text = text[len(nextColor.text):]
            else:  # Need to use only part of the nextColor node
                if nextColor.color is None:
                    nodes.append(text)
                else:
                    nodes.append(createEl(nextColor.color, text))
                # Truncate the nextColor text to what's unconsumed,
                # and put it back into the deque
                nextColor = ColoredText(nextColor.text[len(text):], nextColor.color)
                coloredText.appendleft(nextColor)
                text = ''
        return nodes
    colorizeEl(el, coloredText)

def flattenHighlighting(el):
    # Given a highlighted chunk of markup that is "nested",
    # flattens it into a sequence of text and els with just text,
    # by merging classes upward.
    container = E.div()
    for node in childNodes(el):
        if not isElement(node):
            # raw text
            appendChild(container, node)
        elif not hasChildElements(node):
            # el with just text
            appendChild(container, node)
        else:
            # el with internal structure
            overclass = el.get("class", '') if isElement(el) else ""
            flattened = flattenHighlighting(node)
            for subnode in childNodes(flattened):
                if isElement(subnode):
                    addClass(subnode, overclass)
                    appendChild(container, subnode)
                else:
                    appendChild(container, E.span({"class":overclass},subnode))
    return container

def coloredTextFromRawTokens(text):
    colorFromName = {
        "Token.Comment": "c",
        "Token.Keyword": "k",
        "Token.Literal": "l",
        "Token.Name": "n",
        "Token.Operator": "o",
        "Token.Punctuation": "p",
        "Token.Comment.Multiline": "cm",
        "Token.Comment.Preproc": "cp",
        "Token.Comment.Single": "c1",
        "Token.Comment.Special": "cs",
        "Token.Keyword.Constant": "kc",
        "Token.Keyword.Declaration": "kd",
        "Token.Keyword.Namespace": "kn",
        "Token.Keyword.Pseudo": "kp",
        "Token.Keyword.Reserved": "kr",
        "Token.Keyword.Type": "kt",
        "Token.Literal.Date": "ld",
        "Token.Literal.Number": "m",
        "Token.Literal.String": "s",
        "Token.Name.Attribute": "na",
        "Token.Name.Class": "nc",
        "Token.Name.Constant": "no",
        "Token.Name.Decorator": "nd",
        "Token.Name.Entity": "ni",
        "Token.Name.Exception": "ne",
        "Token.Name.Function": "nf",
        "Token.Name.Label": "nl",
        "Token.Name.Namespace": "nn",
        "Token.Name.Property": "py",
        "Token.Name.Tag": "nt",
        "Token.Name.Variable": "nv",
        "Token.Operator.Word": "ow",
        "Token.Literal.Number.Bin": "mb",
        "Token.Literal.Number.Float": "mf",
        "Token.Literal.Number.Hex": "mh",
        "Token.Literal.Number.Integer": "mi",
        "Token.Literal.Number.Oct": "mo",
        "Token.Literal.String.Backtick": "sb",
        "Token.Literal.String.Char": "sc",
        "Token.Literal.String.Doc": "sd",
        "Token.Literal.String.Double": "s2",
        "Token.Literal.String.Escape": "se",
        "Token.Literal.String.Heredoc": "sh",
        "Token.Literal.String.Interpol": "si",
        "Token.Literal.String.Other": "sx",
        "Token.Literal.String.Regex": "sr",
        "Token.Literal.String.Single": "s1",
        "Token.Literal.String.Symbol": "ss",
        "Token.Name.Variable.Class": "vc",
        "Token.Name.Variable.Global": "vg",
        "Token.Name.Variable.Instance": "vi",
        "Token.Literal.Number.Integer.Long": "il"
    }
    def addCtToList(list, ct):
        if "\n" in ct.text:
            # Break apart the formatting so that the \n is plain text,
            # so it works better with line numbers.
            textBits = ct.text.split("\n")
            list.append(ColoredText(textBits[0], ct.color))
            for bit in textBits[1:]:
                list.append(ColoredText("\n", None))
                list.append(ColoredText(bit, ct.color))
        else:
            list.append(ct)
    textList = collections.deque()
    currentCT = None
    for line in text.split("\n"):
        if not line:
            continue
        tokenName,_,tokenTextRepr = line.partition("\t")
        color = colorFromName.get(tokenName, None)
        text = eval(tokenTextRepr)
        if not text:
            continue
        if not currentCT:
            currentCT = ColoredText(text, color)
        elif currentCT.color == color:
            # Repeated color, merge into current
            currentCT = currentCT._replace(text=currentCT.text + text)
        else:
            addCtToList(textList, currentCT)
            currentCT = ColoredText(text, color)
    if currentCT:
        addCtToList(textList, currentCT)
    return textList


def normalizeLanguageName(lang):
    # Translates some names to ones Pygment understands
    if lang == "aspnet":
        return "aspx-cs"
    if lang in ["markup", "svg"]:
        return "html"
    return lang


def normalizeHighlightMarkers(doc):
    # Translate Prism-style highlighting into Pygment-style
    for el in findAll("[class*=language-], [class*=lang-]", doc):
        match = re.search("(?:lang|language)-(\w+)", el.get("class"))
        if match:
            el.set("highlight", match.group(1))


def lexerFromLang(lang):
    if lang in customLexers:
        return customLexers[lang]
    try:
        return get_lexer_by_name(lang, encoding="utf-8", stripAll=True)
    except pyg.util.ClassNotFound:
        return None


def addLineWrappers(el, numbers=True, start=1, highlights=None):
    # Wrap everything between each top-level newline with a line tag.
    # Add an attr for the line number, and if needed, the end line.
    if highlights is None:
        highlights = set()
    lineWrapper = E.div({"class": "line"})
    for node in childNodes(el, clear=True):
        if isElement(node):
            appendChild(lineWrapper, node)
        else:
            while True:
                if "\n" in node:
                    pre, _, post = node.partition("\n")
                    appendChild(lineWrapper, pre)
                    appendChild(el, E.span({"class": "line-no"}))
                    appendChild(el, lineWrapper)
                    lineWrapper = E.div({"class": "line"})
                    node = post
                else:
                    appendChild(lineWrapper, node)
                    break
    if len(lineWrapper):
        appendChild(el, E.span({"class": "line-no"}))
        appendChild(el, lineWrapper)
    # Number the lines
    lineNumber = start
    for lineNo, node in grouper(childNodes(el), 2):
        if isEmpty(node):
            # Blank line; since I removed the \n from the source
            # and am relying on <div> for lines now,
            # this'll collapse to zero-height and mess things up.
            # Add a single space to keep it one line tall.
            node.text = " "
        if numbers or lineNumber in highlights:
            lineNo.set("line", unicode(lineNumber))
        if lineNumber in highlights:
            addClass(node, "highlight-line")
            addClass(lineNo, "highlight-line")
        internalNewlines = countInternalNewlines(node)
        if internalNewlines:
            for i in range(1, internalNewlines+1):
                if (lineNumber + i) in highlights:
                    addClass(lineNo, "highlight-line")
                    addClass(node, "highlight-line")
                    lineNo.set("line", unicode(lineNumber))
            lineNumber += internalNewlines
            if numbers:
                lineNo.set("line-end", unicode(lineNumber))
        lineNumber += 1
    addClass(el, "line-numbered")
    return el

def countInternalNewlines(el):
    count = 0
    for node in childNodes(el):
        if isElement(node):
            count += countInternalNewlines(node)
        else:
            count += node.count("\n")
    return count


def getHighlightStyles():
    # To regen the styles, edit and run the below
    #from pygments import token
    #from pygments import style
    #class PrismStyle(style.Style):
    #    default_style = "#000000"
    #    styles = {
    #        token.Name: "#0077aa",
    #        token.Name.Tag: "#669900",
    #        token.Name.Builtin: "noinherit",
    #        token.Name.Variable: "#222222",
    #        token.Name.Other: "noinherit",
    #        token.Operator: "#999999",
    #        token.Punctuation: "#999999",
    #        token.Keyword: "#990055",
    #        token.Literal: "#000000",
    #        token.Literal.Number: "#000000",
    #        token.Literal.String: "#a67f59",
    #        token.Comment: "#708090"
    #    }
    #print formatters.HtmlFormatter(style=PrismStyle).get_style_defs('.highlight')
    return '''
.highlight:not(.idl) { background: hsl(24, 20%, 95%); }
code.highlight { padding: .1em; border-radius: .3em; }
pre.highlight, pre > code.highlight { display: block; padding: 1em; margin: .5em 0; overflow: auto; border-radius: 0; }
.highlight .c { color: #708090 } /* Comment */
.highlight .k { color: #990055 } /* Keyword */
.highlight .l { color: #000000 } /* Literal */
.highlight .n { color: #0077aa } /* Name */
.highlight .o { color: #999999 } /* Operator */
.highlight .p { color: #999999 } /* Punctuation */
.highlight .cm { color: #708090 } /* Comment.Multiline */
.highlight .cp { color: #708090 } /* Comment.Preproc */
.highlight .c1 { color: #708090 } /* Comment.Single */
.highlight .cs { color: #708090 } /* Comment.Special */
.highlight .kc { color: #990055 } /* Keyword.Constant */
.highlight .kd { color: #990055 } /* Keyword.Declaration */
.highlight .kn { color: #990055 } /* Keyword.Namespace */
.highlight .kp { color: #990055 } /* Keyword.Pseudo */
.highlight .kr { color: #990055 } /* Keyword.Reserved */
.highlight .kt { color: #990055 } /* Keyword.Type */
.highlight .ld { color: #000000 } /* Literal.Date */
.highlight .m { color: #000000 } /* Literal.Number */
.highlight .s { color: #a67f59 } /* Literal.String */
.highlight .na { color: #0077aa } /* Name.Attribute */
.highlight .nc { color: #0077aa } /* Name.Class */
.highlight .no { color: #0077aa } /* Name.Constant */
.highlight .nd { color: #0077aa } /* Name.Decorator */
.highlight .ni { color: #0077aa } /* Name.Entity */
.highlight .ne { color: #0077aa } /* Name.Exception */
.highlight .nf { color: #0077aa } /* Name.Function */
.highlight .nl { color: #0077aa } /* Name.Label */
.highlight .nn { color: #0077aa } /* Name.Namespace */
.highlight .py { color: #0077aa } /* Name.Property */
.highlight .nt { color: #669900 } /* Name.Tag */
.highlight .nv { color: #222222 } /* Name.Variable */
.highlight .ow { color: #999999 } /* Operator.Word */
.highlight .mb { color: #000000 } /* Literal.Number.Bin */
.highlight .mf { color: #000000 } /* Literal.Number.Float */
.highlight .mh { color: #000000 } /* Literal.Number.Hex */
.highlight .mi { color: #000000 } /* Literal.Number.Integer */
.highlight .mo { color: #000000 } /* Literal.Number.Oct */
.highlight .sb { color: #a67f59 } /* Literal.String.Backtick */
.highlight .sc { color: #a67f59 } /* Literal.String.Char */
.highlight .sd { color: #a67f59 } /* Literal.String.Doc */
.highlight .s2 { color: #a67f59 } /* Literal.String.Double */
.highlight .se { color: #a67f59 } /* Literal.String.Escape */
.highlight .sh { color: #a67f59 } /* Literal.String.Heredoc */
.highlight .si { color: #a67f59 } /* Literal.String.Interpol */
.highlight .sx { color: #a67f59 } /* Literal.String.Other */
.highlight .sr { color: #a67f59 } /* Literal.String.Regex */
.highlight .s1 { color: #a67f59 } /* Literal.String.Single */
.highlight .ss { color: #a67f59 } /* Literal.String.Symbol */
.highlight .vc { color: #0077aa } /* Name.Variable.Class */
.highlight .vg { color: #0077aa } /* Name.Variable.Global */
.highlight .vi { color: #0077aa } /* Name.Variable.Instance */
.highlight .il { color: #000000 } /* Literal.Number.Integer.Long */
'''

def getLineNumberStyles():
    return '''
.line-numbered {
    display: grid !important;
    grid-template-columns: min-content 1fr;
    grid-auto-flow: row;
}
.line-no {
    grid-column: 1;
    color: gray;
}
.line {
    grid-column: 2;
}
.line:hover {
    background: rgba(0,0,0,.05);
}
.line-no[line]::before {
    padding: 0 .5em 0 .1em;
    content: attr(line);
}
.line-no[line-end]::after {
    padding: 0 .5em 0 .1em;
    content: attr(line-end);
}
'''

def getLineHighlightingStyles():
    return '''
.line-numbered {
    display: grid;
    grid-template-columns: min-content 1fr;
    grid-auto-flow: rows;
}
.line-no {
    grid-column: 1;
    color: gray;
}
.line {
    grid-column: 2;
}
.line.highlight-line {
    background: rgba(0,0,0,.05);
}
.line-no.highlight-line[line]::before {
    padding: 0 .5em 0 .1em;
    content: attr(line);
}
.line-no.highlight-line[line-end]::after {
    padding: 0 .5em 0 .1em;
    content: attr(line-end);
}
'''


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return itertools.izip_longest(fillvalue=fillvalue, *args)
