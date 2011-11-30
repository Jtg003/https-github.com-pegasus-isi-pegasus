/*
 * This file or a portion of this file is licensed under the terms of
 * the Globus Toolkit Public License, found in file GTPL, or at
 * http://www.globus.org/toolkit/download/license.html. This notice must
 * appear in redistributions of this file, with or without modification.
 *
 * Redistributions of this Software, with or without modification, must
 * reproduce the GTPL in: (1) the Software, or (2) the Documentation or
 * some other similar material which is provided with the Software (if
 * any).
 *
 * Copyright 1999-2004 University of Chicago and The University of
 * Southern California. All rights reserved.
 */
package org.griphyn.vdl.diagnozer;

import java.io.*;
import java.util.regex.*;

/**
 * Implements a file filter that search by regular expression matches. 
 */
class FindTheRegex implements FilenameFilter
{
  /**
   * Compiled pattern container.
   */
  private Pattern m_pattern;

  /**
   * C'tor
   * @param re is the regular expression to filter with
   */
  public FindTheRegex( String re )
  {
    m_pattern = Pattern.compile(re);
  }

  /**
   * Tests if a specified file should be included in a file list.
   *
   * @param dir the directory in which the file was found.
   * @param name the name of the file.
   * @return <code>true</code> iff the name should be included in the 
   * file list; <code>false</code> otherwise. 
   */
  public boolean accept( File dir, String name )
  {
    Matcher m = m_pattern.matcher(name);
    return m.matches();
  }
}
